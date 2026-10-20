"""The composition root: the one place the four layers are wired to each other.

Exists because nothing below it is allowed to know about the others. The engine may not
import the intelligence layer (Law I), the mapper deliberately does not import the pack
loader, and the pack is data that knows nothing at all. Somewhere they have to meet, and
making that somewhere explicit is what keeps every other module independently debuggable.

Two seams this file exists to hold open:

  * `process_document` takes ONE document, never a list. Fan-out -- Eventarc, Pub/Sub, a
    Cloud Run job per file -- becomes a wrapper around this function rather than a change
    to it (CLAUDE.md 6b).
  * `PackDirectory` is the adapter satisfying the mapper's two-method `FieldDirectory`
    Protocol over a loaded pack plus the precedent store. The mapper never learns that
    either exists.

What this module refuses to do: decide anything. Every decision is made in
engine/resolve.py, which this file calls with plain data. It is wiring, not logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal
from typing import Sequence

from backend.engine import packs as packs_module
from backend.engine import resolve as resolve_module
from backend.engine import units as units_module
from backend.engine.config import DEFAULT_TENANT
from backend.engine.contracts import Authority, ExtractedFact
from backend.engine.gate import DEFAULT_AUTO_THRESHOLD, DEFAULT_REVIEW_THRESHOLD
from backend.intelligence.base import Seam
from backend.intelligence.mapper import FieldDecl, propose_for_fact
from backend.memory.feedback import RoundCounters
from backend.memory.precedents import PrecedentStore


class PackDirectory:
    """Satisfies the mapper's FieldDirectory over a pack and the precedent store.

    A precedent naming a field the pack no longer declares is dropped rather than obeyed:
    a pack can be edited after a precedent was learned, and an analyst's old choice must
    not resurrect a field the customer has since removed.
    """

    def __init__(
        self,
        pack: packs_module.Pack,
        precedents: PrecedentStore | None = None,
    ) -> None:
        self._pack = pack
        self._precedents = precedents
        self._declared = {declaration.name for declaration in pack.fields}

    def fields(self) -> Sequence[FieldDecl]:
        return [
            FieldDecl(
                name=declaration.name,
                label=declaration.label,
                unit=declaration.unit,
                synonyms=tuple(declaration.synonyms),
            )
            for declaration in self._pack.fields
        ]

    def precedent_for(
        self, source_label: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> str | None:
        if self._precedents is None:
            return None
        precedent = self._precedents.lookup(source_label, tenant_id=tenant_id)
        if precedent is None:
            return None
        if precedent.target_field not in self._declared:
            return None
        return precedent.target_field


def declared_fields(pack: packs_module.Pack) -> dict[str, resolve_module.DeclaredField]:
    """The engine's view of the pack: opaque names, types, units and ranges."""
    declared: dict[str, resolve_module.DeclaredField] = {}
    for declaration in pack.fields:
        span = declaration.range
        declared[declaration.name] = resolve_module.DeclaredField(
            name=declaration.name,
            type=declaration.type,
            unit=declaration.unit,
            required=declaration.required,
            range_min=Decimal(str(span.min)) if span and span.min is not None else None,
            range_max=Decimal(str(span.max)) if span and span.max is not None else None,
        )
    return declared


def rule_table(pack: packs_module.Pack) -> units_module.RuleTable:
    """The conversion table, built only from what the pack declares."""
    return units_module.RuleTable.from_rules(
        [
            units_module.ConversionRule(
                id=declaration.id,
                from_unit=declaration.from_unit,
                to_unit=declaration.to_unit,
                factor=Decimal(str(declaration.factor)),
                formula_text=declaration.formula_text,
            )
            for declaration in pack.conversions
        ]
    )


def qualify_unit(fact: ExtractedFact, pack: packs_module.Pack) -> ExtractedFact:
    """Give a fact the unit the pack says its heading implies, if it arrived without one.

    This is the step that makes the declared conversion reachable. An adapter reads a
    column heading and a number; it has no way to know that a particular heading means the
    value is quoted per month rather than per year, and it must not guess -- that would be
    meaning living in the adapter (Law II). The pack declares the heading-to-unit mapping,
    so the pipeline applies it here. Without this the conversion factor is dead data and
    the value is silently wrong by a factor of twelve.
    """
    if fact.raw_unit:
        return fact
    implied = pack.unit_for_label(fact.source_label)
    if implied is None:
        return fact
    return fact.model_copy(update={"raw_unit": implied})


def pack_match_for(
    source_label: str, pack: packs_module.Pack
) -> resolve_module.PackMatch | None:
    """A label the pack itself declares, carrying the declaration's own provenance.

    This exists so the authority order in Law III is real rather than nominal. A label the
    customer declared a synonym for is the customer's own word, so it must rank as
    PACK_QUOTED or PACK_AUTHORED -- above an analyst precedent, far above a model. Routing
    it through the mapper instead would stamp it MODEL, the weakest rank in the system, and
    a stale precedent could then override the customer's own rulebook.

    It also means an exact pack synonym consults no model at all, which is the cheapest
    path through the pipeline and the most defensible.
    """
    name = pack.field_for_label(source_label)
    if name is None:
        return None
    declaration = next((f for f in pack.fields if f.name == name), None)
    if declaration is None:
        return None
    return resolve_module.PackMatch(
        target_field=name, provenance=declaration.provenance.tag
    )


@dataclass
class DocumentOutcome:
    """Everything one document produced, plus the counters the round report needs."""

    document_id: str
    resolutions: list[resolve_module.Resolution] = dataclass_field(default_factory=list)
    counters: RoundCounters = dataclass_field(default_factory=RoundCounters)
    unreadable_reason: str | None = None

    @property
    def mappings(self):
        return [resolution.mapping for resolution in self.resolutions]


def process_document(
    document_id: str,
    facts: Sequence[ExtractedFact],
    *,
    pack: packs_module.Pack,
    precedents: PrecedentStore | None = None,
    seam: Seam | None = None,
    tenant_id: str = DEFAULT_TENANT,
    document_name: str | None = None,
    auto_threshold: float = DEFAULT_AUTO_THRESHOLD,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    thresholds_are_calibrated: bool = False,
) -> DocumentOutcome:
    """One document in, one outcome out. Never a list: fan-out is a wrapper.

    `seam` may be None. With no provider configured the run still happens: everything with
    a precedent or a pack synonym resolves deterministically and the rest goes to the
    review tray. A run always produces a result and an honest account of itself.
    """
    directory = PackDirectory(pack, precedents)
    declared = declared_fields(pack)
    table = rule_table(pack)
    outcome = DocumentOutcome(document_id=document_id)

    for fact in facts:
        qualified = qualify_unit(fact, pack)

        # Highest authority first, and it costs nothing: a label the pack declares is
        # settled by the pack, so no model is consulted and no precedent can override it.
        match = pack_match_for(qualified.source_label, pack)
        proposal = None
        if match is None:
            proposal = propose_for_fact(
                qualified,
                directory,
                seam=seam,
                tenant_id=tenant_id,
                document_name=document_name,
            ).outcome

        resolution = resolve_module.resolve(
            qualified,
            declared=declared,
            table=table,
            pack_match=match,
            precedent=None,
            proposal=proposal,
            mapping_id=f"map-{uuid.uuid4().hex[:12]}",
            auto_threshold=auto_threshold,
            review_threshold=review_threshold,
            thresholds_are_calibrated=thresholds_are_calibrated,
        )

        outcome.resolutions.append(resolution)

        # Read the authority off the resolution rather than off the candidate list: the
        # resolution is what actually decided, and a precedent naming an undeclared field
        # is dropped by then, so counting candidates would credit a precedent that did
        # no work.
        by_precedent = resolution.authority is Authority.ANALYST
        outcome.counters.observe(
            used_model=resolution.used_model,
            model_call_skipped=resolution.model_call_skipped,
            by_precedent=by_precedent,
        )
        if by_precedent and precedents is not None:
            precedents.note_applied(qualified.source_label, tenant_id=tenant_id)

    return outcome
