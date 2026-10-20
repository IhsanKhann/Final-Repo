"""Agent 2. Retrieval is deterministic; the model only arbitrates, and only from a list.

Exists so that "intelligent field mapping" is auditable: candidates are retrieved by
exact synonym, then precedent, then fuzzy ratio -- all pure, all testable with no key and
no network -- and a model is called only when that retrieval is genuinely ambiguous. One
strong candidate resolves with no model call at all, which is what makes round 2 cheaper
rather than just re-prompted.

What this module refuses to do:
  * It refuses to let the model name a field the pack does not declare. The enforced
    schema closes `target_field` over the retrieved candidates (prompts.py) and this
    module checks the answer against that list again -- a schema is a request, not a
    guarantee. An out-of-list answer is one retry, then `Unavailable`, which the gate
    writes as `missing`. It is never repaired into the nearest declared field.
  * It refuses to import the pack loader. It depends on the `FieldDirectory` Protocol
    below -- "something that can give me synonyms and precedents" -- so this block
    compiles and tests standalone against a fake while block 3 is still being written.
  * It refuses to invent a candidate. If the pack declares nothing that matches, the
    result carries no proposal and no model call was made: `missing` is a real answer.
  * It refuses to decide. It returns a `Proposal`; `engine/resolve.py` decides, and a
    precedent or a QUOTED pack rule outranks anything here (contracts.Authority).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal, Mapping, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from backend.engine.config import DEFAULT_TENANT
from backend.engine.contracts import (
    Authority,
    ExtractedFact,
    Proposal,
    ProposalOutcome,
    Unavailable,
)
from backend.intelligence import prompts
from backend.intelligence.base import Seam

# --- The narrow Protocol this block depends on --------------------------------


class FieldDecl(BaseModel):
    """One field as the pack declares it. The pack owns the vocabulary; we only read it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    synonyms: tuple[str, ...] = ()
    unit: str | None = None
    label: str | None = None


@runtime_checkable
class FieldDirectory(Protocol):
    """Something that can give me synonyms and precedents.

    Deliberately two methods wide. `backend/engine/packs.py` (block 3) and
    `backend/memory/` (block 8) satisfy it together behind one adapter; a test fake
    satisfies it in four lines. Nothing here imports either, so this module is importable
    before they exist.
    """

    def fields(self) -> Sequence[FieldDecl]:
        """Every field the pack declares. The model may not name anything outside this."""
        ...

    def precedent_for(self, source_label: str, *, tenant_id: str = DEFAULT_TENANT) -> str | None:
        """A field an analyst already chose for this label, or None."""
        ...


# --- Retrieval (pure) ---------------------------------------------------------

Via = Literal["exact-synonym", "precedent", "fuzzy"]

#: Above this, a fuzzy match is treated as strong enough to resolve without a model.
#: Deliberately high: the cost of a needless model call is pennies, the cost of a wrong
#: silent mapping is the product's credibility.
STRONG_FUZZY_RATIO = 0.92
#: Below this a fuzzy match is not worth showing the model at all.
FUZZY_FLOOR = 0.55

_EXACT_SCORE = 0.99
_PRECEDENT_SCORE = 0.97

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_label(label: str) -> str:
    """Casefold, strip punctuation, collapse whitespace, so 'Net Rate (%)' meets 'net_rate_pct'."""
    return _NON_ALNUM.sub(" ", (label or "").strip().lower()).strip()


def similarity(a: str, b: str) -> float:
    """difflib ratio on normalized labels. stdlib on purpose: no new dependency."""
    return SequenceMatcher(None, normalize_label(a), normalize_label(b)).ratio()


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_field: str
    score: float = Field(ge=0.0, le=1.0)
    via: Via
    #: The synonym, field name or precedent label that produced the match. Shown to the
    #: model and to the reviewer, so a bad synonym in the pack is visible as a bad synonym.
    matched_on: str
    unit: str | None = None
    synonyms: tuple[str, ...] = ()

    @property
    def strong(self) -> bool:
        return self.via in ("exact-synonym", "precedent") or self.score >= STRONG_FUZZY_RATIO


class CandidateSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_label: str
    candidates: tuple[Candidate, ...] = ()

    @property
    def strong(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.strong)

    @property
    def allowed_fields(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(c.target_field for c in self.candidates))

    def resolves_without_a_model(self) -> Candidate | None:
        """Exactly one strong candidate, and nothing strong disagreeing with it."""
        strong = self.strong
        if len(strong) == 1:
            return strong[0]
        if strong and len({c.target_field for c in strong}) == 1:
            # Several routes, one answer: synonym and precedent agreeing is the cheapest
            # certainty in the system, not an ambiguity.
            return max(strong, key=lambda c: c.score)
        return None


def retrieve_candidates(
    source_label: str,
    directory: FieldDirectory,
    *,
    tenant_id: str = DEFAULT_TENANT,
    limit: int = 5,
    fuzzy_floor: float = FUZZY_FLOOR,
) -> CandidateSet:
    """exact synonym -> precedent -> fuzzy ratio. Pure: no model, no key, no network.

    Order is the authority order read backwards: what the pack says a label is called
    beats what an analyst inferred, which beats what two strings look like.
    """
    declared = list(directory.fields())
    by_name = {d.name: d for d in declared}
    normalized = normalize_label(source_label)
    found: dict[str, Candidate] = {}

    def offer(candidate: Candidate) -> None:
        kept = found.get(candidate.target_field)
        if kept is None or candidate.score > kept.score:
            found[candidate.target_field] = candidate

    # 1. exact synonym (or the field's own name / label), normalized both sides
    for decl in declared:
        aliases = [decl.name, *(decl.label,), *decl.synonyms]
        for alias in aliases:
            if alias and normalize_label(alias) == normalized:
                offer(
                    Candidate(
                        target_field=decl.name,
                        score=_EXACT_SCORE,
                        via="exact-synonym",
                        matched_on=alias,
                        unit=decl.unit,
                        synonyms=decl.synonyms,
                    )
                )
                break

    # 2. precedent: what an analyst already chose for this label
    learned = directory.precedent_for(source_label, tenant_id=tenant_id)
    if learned:
        decl = by_name.get(learned)
        # A precedent naming a field the pack no longer declares is stale, not law.
        if decl is not None:
            offer(
                Candidate(
                    target_field=decl.name,
                    score=_PRECEDENT_SCORE,
                    via="precedent",
                    matched_on=source_label,
                    unit=decl.unit,
                    synonyms=decl.synonyms,
                )
            )

    # 3. fuzzy ratio against every declared name, label and synonym
    for decl in declared:
        if decl.name in found:
            continue
        best = 0.0
        best_on = decl.name
        for alias in [decl.name, *(decl.label,), *decl.synonyms]:
            if not alias:
                continue
            ratio = similarity(source_label, alias)
            if ratio > best:
                best, best_on = ratio, alias
        if best >= fuzzy_floor:
            offer(
                Candidate(
                    target_field=decl.name,
                    score=round(best, 4),
                    via="fuzzy",
                    matched_on=best_on,
                    unit=decl.unit,
                    synonyms=decl.synonyms,
                )
            )

    ranked = sorted(found.values(), key=lambda c: (-c.score, c.target_field))
    return CandidateSet(source_label=source_label, candidates=tuple(ranked[: max(1, limit)]))


# --- The result ---------------------------------------------------------------


@dataclass(frozen=True)
class MapperResult:
    """What the mapper returns, with the two facts the round report needs.

    `outcome` is `None` -- not an `Unavailable` -- when the pack declares nothing that
    could match the label. That is a deterministic `missing`, not a failure: there was
    nothing to ask about, so no model was called and no provider was at fault.
    `engine/resolve.py` already takes `Proposal | None`.
    """

    outcome: ProposalOutcome | None
    used_model: bool
    candidates: tuple[Candidate, ...]
    #: Set only when outcome is None.
    missing_reason: str | None = None

    @property
    def proposal(self) -> Proposal | None:
        return self.outcome if isinstance(self.outcome, Proposal) else None

    @property
    def unavailable(self) -> Unavailable | None:
        return self.outcome if isinstance(self.outcome, Unavailable) else None


#: What `Proposal.model` says when nothing was called. Honest in the evidence drawer and
#: countable for RoundReport.model_calls_skipped.
NO_MODEL = "none (deterministic retrieval)"


def _deterministic_proposal(
    source_label: str, candidate: Candidate, *, confidence: float | None = None
) -> Proposal:
    reason = (
        f"Resolved with no model call: {candidate.via} match on "
        f"{candidate.matched_on!r} -> {candidate.target_field}."
    )
    return Proposal(
        source_label=source_label,
        target_field=candidate.target_field,
        confidence=candidate.score if confidence is None else confidence,
        reason=reason,
        model=NO_MODEL,
        prompt_version=prompts.NO_PROMPT,
        # A precedent is an analyst's decision, and it keeps that authority even though a
        # mapper call is what surfaced it. resolve.py reads this, so getting it wrong
        # would let a model proposal outrank a human.
        authority=Authority.ANALYST if candidate.via == "precedent" else Authority.MODEL,
    )


# --- The flow -----------------------------------------------------------------


def propose_mapping(
    source_label: str,
    directory: FieldDirectory,
    *,
    seam: Seam | None = None,
    tenant_id: str = DEFAULT_TENANT,
    sample_value: str | None = None,
    sample_unit: str | None = None,
    context: str | None = None,
    document_name: str | None = None,
    limit: int = 5,
) -> MapperResult:
    """retrieve -> one strong candidate? resolve free : ask the model from the list.

    Never raises: every exit is a `MapperResult` whose outcome is a Proposal, an
    Unavailable, or None.
    """
    candidate_set = retrieve_candidates(
        source_label, directory, tenant_id=tenant_id, limit=limit
    )
    candidates = candidate_set.candidates

    if not candidates:
        return MapperResult(
            outcome=None,
            used_model=False,
            candidates=(),
            missing_reason=(
                f"no field declared in the pack matches {source_label!r} by synonym, "
                "precedent or similarity; no model was called"
            ),
        )

    settled = candidate_set.resolves_without_a_model()
    if settled is not None:
        return MapperResult(
            outcome=_deterministic_proposal(source_label, settled),
            used_model=False,
            candidates=candidates,
        )

    if seam is None:
        # Ambiguous and nothing to arbitrate with. The tray, not the best guess.
        return MapperResult(
            outcome=Unavailable(
                reason="no-key",
                detail=(
                    f"{len(candidates)} candidates for {source_label!r} and no model "
                    "configured to choose between them"
                ),
            ),
            used_model=False,
            candidates=candidates,
        )

    allowed = candidate_set.allowed_fields
    schema = prompts.mapping_choice_schema(allowed)
    user = prompts.render_mapping_user(
        source_label=source_label,
        candidates=[c.model_dump() for c in candidates],
        sample_value=sample_value,
        sample_unit=sample_unit,
        context=context,
        document_name=document_name,
    )

    def validate(payload: Mapping[str, Any]) -> str | None:
        """The out-of-list rejection. One retry upstream, then Unavailable."""
        chosen = payload.get("target_field")
        if not isinstance(chosen, str) or not chosen.strip():
            return "reply carried no target_field"
        if chosen not in allowed:
            return (
                f"model chose {chosen!r}, which the pack does not declare; "
                f"allowed: {list(allowed)}"
            )
        if "reason" not in payload or not str(payload.get("reason") or "").strip():
            return "reply carried no reason; an unarguable mapping is not usable"
        return None

    def build(payload: Mapping[str, Any]) -> Proposal:
        confidence = payload.get("confidence")
        return Proposal(
            source_label=source_label,
            target_field=str(payload["target_field"]),
            confidence=float(confidence) if confidence is not None else 0.5,
            reason=str(payload["reason"]).strip(),
            model=seam.model,
            prompt_version=seam.prompt_version or prompts.PROMPT_VERSION,
            authority=Authority.MODEL,
        )

    outcome = seam.propose(
        system=prompts.MAPPER_SYSTEM,
        user=user,
        schema=schema,
        build=build,
        validate=validate,
    )
    return MapperResult(outcome=outcome, used_model=True, candidates=candidates)


def propose_for_fact(
    fact: ExtractedFact,
    directory: FieldDirectory,
    *,
    seam: Seam | None = None,
    tenant_id: str = DEFAULT_TENANT,
    document_name: str | None = None,
    limit: int = 5,
) -> MapperResult:
    """The pipeline's entry point: one fact, never a list, so fan-out is a wrapper."""
    return propose_mapping(
        fact.source_label,
        directory,
        seam=seam,
        tenant_id=tenant_id,
        sample_value=fact.raw_value,
        sample_unit=fact.raw_unit,
        context=fact.context,
        document_name=document_name,
        limit=limit,
    )


__all__ = [
    "FUZZY_FLOOR",
    "NO_MODEL",
    "STRONG_FUZZY_RATIO",
    "Candidate",
    "CandidateSet",
    "FieldDecl",
    "FieldDirectory",
    "MapperResult",
    "Via",
    "normalize_label",
    "propose_for_fact",
    "propose_mapping",
    "retrieve_candidates",
    "similarity",
]
