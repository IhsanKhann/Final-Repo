"""The decision. One pure function turns proposals and declarations into one Mapping.

Exists so that exactly one place in the system decides what a value is, and so that place
contains no model call (Law I). Proposals arrive from outside as plain data. The same
inputs and the same version produce the same output, bit for bit, which is the only reason
the round reports mean anything.

The authority order is the product's whole claim, so it is enforced here and nowhere else:

    PACK_QUOTED  >  PACK_AUTHORED  >  ANALYST  >  MODEL

A model proposal is the weakest thing in the system. A rule the customer quoted from their
own document is the strongest. An analyst sits between them, above the model because they
are accountable and below the pack because the pack is the customer's own word.

What this module refuses to do:
  * It refuses to accept a target field the pack does not declare, whoever named it. A
    model that invents a field gets `missing`, not the benefit of the doubt.
  * It refuses to construct a value without provenance -- the contract makes that
    impossible, and this module does not work around it.
  * It refuses to know what any field means. Field names, units and synonyms arrive as
    opaque strings from the pack (Law II).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.engine import gate as gate_module
from backend.engine import units as units_module
from backend.engine.contracts import (
    Authority,
    ExtractedFact,
    Mapping,
    Precedent,
    Proposal,
    Unavailable,
    ValidationResult,
)

ProvenanceTag = Literal["QUOTED", "AUTHORED", "MEASURED"]


class DeclaredField(BaseModel):
    """The engine's view of one field the pack declares. Opaque names, no meaning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: Literal["number", "string", "date", "boolean"]
    unit: str | None = None
    required: bool = False
    range_min: Decimal | None = None
    range_max: Decimal | None = None


class PackMatch(BaseModel):
    """A deterministic hit against the pack's own declarations. No model involved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_field: str
    provenance: ProvenanceTag
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Resolution(BaseModel):
    """The mapping plus the facts the round report needs to prove the loop is real."""

    model_config = ConfigDict(extra="forbid")

    mapping: Mapping
    authority: Authority | None = None
    used_model: bool = False
    #: True when a precedent or a pack rule answered and a model call was therefore not
    #: needed. Counting these is what distinguishes learning from re-prompting.
    model_call_skipped: bool = False


def _authority_of(tag: ProvenanceTag) -> Authority:
    # MEASURED is a census over the customer's data, not a citation, so it ranks with
    # AUTHORED rather than with QUOTED. Only a real quote earns the top rank.
    return Authority.PACK_QUOTED if tag == "QUOTED" else Authority.PACK_AUTHORED


def _validate(value: str | None, field: DeclaredField) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    if value is None:
        return results

    if field.type == "number":
        number = units_module.parse_numeric(value)
        ok = number is not None
        results.append(
            ValidationResult(
                name="type",
                ok=ok,
                message=(
                    f"{field.name} reads as a number"
                    if ok
                    else f"{field.name} expects a number, got {value!r}"
                ),
            )
        )
        if number is not None and (field.range_min is not None or field.range_max is not None):
            low = field.range_min
            high = field.range_max
            in_range = (low is None or number >= low) and (high is None or number <= high)
            results.append(
                ValidationResult(
                    name="range",
                    ok=in_range,
                    message=(
                        f"{value} within declared range [{low}, {high}]"
                        if in_range
                        else f"{value} outside declared range [{low}, {high}]"
                    ),
                )
            )
    return results


def resolve(
    fact: ExtractedFact,
    *,
    declared: dict[str, DeclaredField],
    table: units_module.RuleTable,
    pack_match: PackMatch | None = None,
    precedent: Precedent | None = None,
    proposal: Proposal | Unavailable | None = None,
    mapping_id: str,
    auto_threshold: float = gate_module.DEFAULT_AUTO_THRESHOLD,
    review_threshold: float = gate_module.DEFAULT_REVIEW_THRESHOLD,
    thresholds_are_calibrated: bool = False,
) -> Resolution:
    """Decide one field. Pure: no I/O, no clock, no model, no config read."""

    forced: list[gate_module.ForcedReview] = []
    chosen: str | None = None
    authority: Authority | None = None
    confidence = 0.0
    reason_parts: list[str] = []
    used_model = False
    model_call_skipped = False
    constrained_proposal = False

    # 1. Highest authority first. The pack is the customer's own word.
    if pack_match is not None and pack_match.target_field in declared:
        chosen = pack_match.target_field
        authority = _authority_of(pack_match.provenance)
        confidence = pack_match.confidence
        model_call_skipped = True
        reason_parts.append(
            f"the pack declares this source label for {chosen} "
            f"({pack_match.provenance.lower()})"
        )

    # 2. Then an analyst precedent: accountable, and it costs no model call.
    elif precedent is not None and precedent.target_field in declared:
        chosen = precedent.target_field
        authority = Authority.ANALYST
        confidence = 1.0
        model_call_skipped = True
        reason_parts.append(
            f"an analyst previously mapped this source label to {chosen}, "
            "so no model was consulted"
        )

    # 3. Last and weakest, a model proposal -- and only inside the declared fields.
    elif isinstance(proposal, Proposal):
        # The proposer states whether a model was consulted and with what authority. A
        # precedent surfaced through the mapper keeps ANALYST authority, so overwriting
        # this with MODEL here would let a model proposal outrank a human decision.
        used_model = proposal.used_model
        model_call_skipped = not proposal.used_model
        if proposal.target_field in declared:
            chosen = proposal.target_field
            authority = proposal.authority
            confidence = proposal.confidence
            reason_parts.append(proposal.reason)
            # Retrieval constrained the choice to declared fields, so a low score here
            # means "I am unsure which of your fields this is", not "I may have invented
            # one". The gate offers it to a reviewer instead of discarding it.
            constrained_proposal = proposal.used_model
        else:
            forced.append("out-of-declared-fields")
            reason_parts.append(
                f"the model named {proposal.target_field!r}, which the pack does not "
                "declare, so it was not accepted"
            )

    elif isinstance(proposal, Unavailable):
        forced.append("intelligence-unavailable")
        reason_parts.append(
            f"intelligence was unavailable ({proposal.reason}), so this field goes to a "
            "human rather than to a guess"
        )

    # Convert, if a field was chosen and the pack declares a target unit for it.
    conversion_outcome: units_module.ConversionOutcome | None = None
    value: str | None = None
    unit: str | None = None

    if chosen is not None:
        field = declared[chosen]
        conversion_outcome = units_module.convert(fact.raw_value, fact.raw_unit, field.unit, table)
        value = conversion_outcome.value
        unit = conversion_outcome.unit
        if conversion_outcome.magnitude_suspect:
            forced.append("magnitude-suspect")
        if conversion_outcome.outcome == "no-rule":
            forced.append("no-conversion-rule")
            reason_parts.append(conversion_outcome.detail or "no declared conversion")
        if conversion_outcome.outcome == "unparseable":
            value = None

    validations = _validate(value, declared[chosen]) if chosen is not None else []
    if any(not v.ok for v in validations):
        forced.append("validation-failed")

    decision = gate_module.decide(
        gate_module.GateInput(
            confidence=confidence,
            has_value=value is not None and chosen is not None,
            has_provenance=fact.source_location is not None,
            forced_review=tuple(dict.fromkeys(forced)),
            verifier_rejected=False,
            constrained_proposal=constrained_proposal,
        ),
        auto_threshold=auto_threshold,
        review_threshold=review_threshold,
        thresholds_are_calibrated=thresholds_are_calibrated,
    )

    reason_parts.append(decision.reason)

    mapping = Mapping(
        id=mapping_id,
        document_id=fact.document_id,
        record_key=fact.record_key,
        source_label=fact.source_label,
        target_field=chosen or "",
        raw_value=fact.raw_value,
        raw_unit=fact.raw_unit,
        value=value if value is not None else "",
        unit=unit,
        confidence=confidence,
        status=decision.status,
        reason="; ".join(p for p in reason_parts if p),
        conversion=conversion_outcome.conversion if conversion_outcome else None,
        validations=validations,
        source_location=fact.source_location,
    )

    # Resolution carries RUN facts -- who decided, whether a model was consulted. The
    # record key is a field fact and now travels on the Mapping itself, so there is one
    # source for it rather than two that can disagree.
    return Resolution(
        mapping=mapping,
        authority=authority,
        used_model=used_model,
        model_call_skipped=model_call_skipped,
    )


def validate_record(
    values: dict[str, str],
    cross_field_rules: list[tuple[str, str, str]],
) -> list[ValidationResult]:
    """Cross-field validations, declared by the pack as (left, operator, right).

    Kept separate from resolve() because a cross-field rule is a property of a record, not
    of a field, and folding it into resolve would make the per-field function depend on
    fields it has not seen yet.
    """
    results: list[ValidationResult] = []
    for left, operator, right in cross_field_rules:
        left_value = units_module.parse_numeric(values.get(left, ""))
        right_value = units_module.parse_numeric(values.get(right, ""))
        if left_value is None or right_value is None:
            continue
        if operator == ">=":
            ok = left_value >= right_value
        elif operator == "<=":
            ok = left_value <= right_value
        elif operator == ">":
            ok = left_value > right_value
        elif operator == "<":
            ok = left_value < right_value
        elif operator == "==":
            ok = left_value == right_value
        else:
            raise ValueError(f"the pack declares an operator this engine cannot apply: {operator!r}")
        results.append(
            ValidationResult(
                name=f"{left} {operator} {right}",
                ok=ok,
                message=(
                    f"{left}={left_value} {operator} {right}={right_value}"
                    if ok
                    else f"{left}={left_value} is not {operator} {right}={right_value}"
                ),
            )
        )
    return results
