"""The feedback loop is real: round 2 resolves what round 1 flagged, with no model call.

This is the test behind the claim the whole product rests on, so it checks the mechanism
rather than the headline. An improvement that came from a second roll of the same dice
would show the same accuracy delta and zero skipped model calls, and would be worthless.
What makes round 2 better is that a human decision is now stored and the model is not
consulted at all.

It also pins the comparability check, because a delta computed across rounds whose inputs
moved is a false claim made with a chart.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.engine.contracts import (
    Authority,
    ExtractedFact,
    MappingPatchPayload,
    Proposal,
    RoundReport,
    SourceLocationSheet,
)
from backend.engine.resolve import DeclaredField, resolve
from backend.engine.rounds import compare, count_lanes, fingerprint_documents
from backend.engine.units import ConversionRule, RuleTable
from backend.memory.feedback import RoundCounters, apply_patch
from backend.memory.precedents import SqlitePrecedentStore

TABLE = RuleTable.from_rules(
    [
        ConversionRule(
            id="c1",
            from_unit="u_month",
            to_unit="u_year",
            factor=Decimal(12),
            formula_text="x 12 (monthly -> annual)",
        )
    ]
)
DECLARED = {"f_annual": DeclaredField(name="f_annual", type="number", unit="u_year")}


@pytest.fixture()
def store(tmp_path):
    return SqlitePrecedentStore(tmp_path / "memory.db")


def _fact() -> ExtractedFact:
    return ExtractedFact(
        document_id="doc-1",
        source_label="an unlisted terminology variant",
        raw_value="0.3383",
        raw_unit="u_month",
        source_location=SourceLocationSheet(sheet="Rates", cell="B12"),
    )


def _proposal(confidence: float) -> Proposal:
    return Proposal(
        source_label="an unlisted terminology variant",
        target_field="f_annual",
        confidence=confidence,
        reason="the label names a monthly nominal quote",
        model="pinned-model",
        prompt_version="v1",
    )


def test_a_flagged_field_becomes_auto_accepted_after_one_correction(store):
    first = resolve(
        _fact(),
        declared=DECLARED,
        table=TABLE,
        precedent=store.lookup("an unlisted terminology variant"),
        proposal=_proposal(0.72),
        mapping_id="m1",
    )
    assert first.mapping.status == "review", "a 0.72 proposal should land in the middle lane"
    assert first.used_model is True

    apply_patch(
        first.mapping,
        MappingPatchPayload(action="accept"),
        store,
        prior_authority=Authority.MODEL,
    )

    second = resolve(
        _fact(),
        declared=DECLARED,
        table=TABLE,
        precedent=store.lookup("an unlisted terminology variant"),
        proposal=None,
        mapping_id="m2",
    )
    assert second.mapping.status == "auto"
    assert second.authority is Authority.ANALYST


def test_round_two_consults_no_model_at_all(store):
    """The mechanism, not the metric. This is what separates learning from re-prompting."""
    first = resolve(
        _fact(), declared=DECLARED, table=TABLE, proposal=_proposal(0.72), mapping_id="m1"
    )
    apply_patch(
        first.mapping, MappingPatchPayload(action="accept"), store, prior_authority=Authority.MODEL
    )

    counters = RoundCounters()
    precedent = store.lookup("an unlisted terminology variant")
    second = resolve(
        _fact(), declared=DECLARED, table=TABLE, precedent=precedent, proposal=None, mapping_id="m2"
    )
    counters.observe(
        used_model=second.used_model,
        model_call_skipped=second.model_call_skipped,
        by_precedent=precedent is not None,
    )

    assert counters.model_calls_made == 0
    assert counters.model_calls_skipped == 1
    assert counters.precedents_applied == 1


def test_the_learned_value_is_identical_to_what_the_analyst_chose(store):
    """Cheaper and faster is only worth anything if the answer did not change."""
    first = resolve(
        _fact(), declared=DECLARED, table=TABLE, proposal=_proposal(0.72), mapping_id="m1"
    )
    outcome = apply_patch(
        first.mapping, MappingPatchPayload(action="accept"), store, prior_authority=Authority.MODEL
    )
    second = resolve(
        _fact(),
        declared=DECLARED,
        table=TABLE,
        precedent=store.lookup("an unlisted terminology variant"),
        mapping_id="m2",
    )
    assert second.mapping.value == outcome.response.mapping.value


def test_a_rejection_teaches_nothing(store):
    """A reject says which field is wrong, not which is right. Inventing it is forbidden."""
    first = resolve(
        _fact(), declared=DECLARED, table=TABLE, proposal=_proposal(0.72), mapping_id="m1"
    )
    outcome = apply_patch(
        first.mapping, MappingPatchPayload(action="reject"), store, prior_authority=Authority.MODEL
    )
    assert outcome.response.learned is False
    assert store.lookup("an unlisted terminology variant") is None


def test_accepting_a_pack_resolved_field_writes_no_precedent(store):
    """A pack rule outranks a precedent, so such a precedent could never do any work."""
    first = resolve(
        _fact(), declared=DECLARED, table=TABLE, proposal=_proposal(0.95), mapping_id="m1"
    )
    outcome = apply_patch(
        first.mapping,
        MappingPatchPayload(action="accept"),
        store,
        prior_authority=Authority.PACK_QUOTED,
    )
    assert outcome.response.learned is False
    assert store.lookup("an unlisted terminology variant") is None


def test_a_term_corrected_three_times_becomes_a_proposal_never_an_edit(store):
    """Round 3 promotion: the system proposes, the customer authors."""
    for index in range(3):
        resolution = resolve(
            _fact(), declared=DECLARED, table=TABLE, proposal=_proposal(0.72), mapping_id=f"m{index}"
        )
        apply_patch(
            resolution.mapping,
            MappingPatchPayload(action="accept"),
            store,
            prior_authority=Authority.MODEL,
            event_id=f"fb-{index}",
        )

    candidates = store.promotion_candidates(threshold=3)
    assert len(candidates) == 1
    assert candidates[0].corrections == 3
    assert candidates[0].status == "PROPOSED", "a promotion must never apply itself"


# --- comparability --------------------------------------------------------------


def _report(round_number: int, **overrides) -> RoundReport:
    base = dict(
        round=round_number,
        pack_id="p1",
        pack_version="1.0.0",
        model="pinned-model",
        temperature=0.0,
        prompt_version="v1",
        documents_fingerprint="abc123",
        docs=6,
        fields=30,
        auto_accepted=20,
        flagged=8,
        missing=2,
        mapping_accuracy=0.80,
        conversion_correctness=1.0,
        precedents_applied=0,
        model_calls_skipped=0,
        analyst_minutes_saved=30.0,
        cost_usd=0.10,
    )
    base.update(overrides)
    return RoundReport(**base)


def test_two_rounds_on_the_same_inputs_report_a_delta():
    previous = _report(1)
    current = _report(2, auto_accepted=27, flagged=2, mapping_accuracy=0.93, precedents_applied=7,
                      model_calls_skipped=7)
    compared = compare(current, previous)
    assert compared.comparable is True
    assert compared.delta_vs_previous is not None
    assert compared.delta_vs_previous["mapping_accuracy"] == pytest.approx(0.13)
    assert compared.delta_vs_previous["model_calls_skipped"] == 7


@pytest.mark.parametrize(
    "moved",
    [
        {"model": "a-different-model"},
        {"temperature": 0.7},
        {"prompt_version": "v2"},
        {"pack_version": "1.1.0"},
        {"documents_fingerprint": "different"},
    ],
)
def test_a_round_that_changed_a_controlled_variable_reports_not_comparable(moved):
    """All five controlled variables, because any one of them voids the comparison."""
    compared = compare(_report(2, **moved), _report(1))
    assert compared.comparable is False
    assert compared.delta_vs_previous is None
    assert list(moved)[0] in (compared.not_comparable_reason or "")


def test_the_document_fingerprint_ignores_order_but_not_content():
    assert fingerprint_documents(["a", "b"]) == fingerprint_documents(["b", "a"])
    assert fingerprint_documents(["a", "b"]) != fingerprint_documents(["a", "c"])


def test_only_auto_accepted_fields_count_as_effort_saved():
    """A field that went to review did not save the analyst anything."""
    from backend.engine.rounds import analyst_minutes_saved

    assert analyst_minutes_saved(20, 1.5) == 30.0
    assert analyst_minutes_saved(0, 1.5) == 0.0


def test_lane_counting_treats_approved_as_auto_and_rejected_as_missing():
    from backend.engine.contracts import Mapping

    def mapping(status: str, mapping_id: str) -> Mapping:
        kwargs = dict(
            id=mapping_id, document_id="d", source_label="l", target_field="f_annual",
            raw_value="1", value="1", confidence=0.5, status=status,
        )
        if status in ("auto", "approved"):
            kwargs["source_location"] = SourceLocationSheet(sheet="S", cell="A1")
        return Mapping(**kwargs)

    auto, flagged, missing = count_lanes(
        [
            mapping("auto", "1"),
            mapping("approved", "2"),
            mapping("review", "3"),
            mapping("missing", "4"),
            mapping("rejected", "5"),
        ]
    )
    assert (auto, flagged, missing) == (2, 1, 2)
