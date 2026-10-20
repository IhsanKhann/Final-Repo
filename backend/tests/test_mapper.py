"""Agent 2: deterministic retrieval, a model that may only arbitrate, and a hard list.

The behaviours these tests protect, in the order they matter:
  1. An exact synonym or a precedent resolves with NO model call at all. The injected
     transport is asserted never to have been invoked, because "cheaper in round 2" is a
     claim about calls that did not happen, not about a faster prompt.
  2. The model may not name a field the pack does not declare. An out-of-list answer is
     one retry, then Unavailable -- which the gate writes as `missing`. It is never
     repaired into the nearest declared field.
  3. Retrieval is a pure function over a fake directory, so all of this runs with no key
     and no network.

Field names here are deliberately synthetic. The pack owns the vocabulary (Law II), and a
test that hard-codes a customer's nouns would be testing the pack, not the mapper.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from backend.engine.contracts import Authority, ExtractedFact, Proposal, Unavailable
from backend.intelligence import mapper, prompts
from backend.intelligence.base import Seam, TransportReply
from backend.intelligence.providers import PROVIDERS

# --- fakes --------------------------------------------------------------------


class FakeDirectory:
    """The narrow Protocol, four lines of it. Block 3's pack loader satisfies it later."""

    def __init__(
        self,
        fields: Sequence[mapper.FieldDecl],
        precedents: dict[str, str] | None = None,
    ) -> None:
        self._fields = list(fields)
        self._precedents = precedents or {}
        self.precedent_lookups: list[str] = []

    def fields(self) -> Sequence[mapper.FieldDecl]:
        return list(self._fields)

    def precedent_for(self, source_label: str, *, tenant_id: str = "demo") -> str | None:
        self.precedent_lookups.append(source_label)
        return self._precedents.get(source_label)


class NeverCalledTransport:
    """Fails loudly if touched. 'No model call' has to be an assertion, not a hope."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url, *, headers, body, timeout_s):
        self.calls.append({"url": url, "body": dict(body)})
        raise AssertionError("a model was called where no model call was permitted")


class ScriptedTransport:
    """Replays queued replies and records the bodies it was given. The last reply repeats."""

    def __init__(self, *replies: TransportReply) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def post(self, url, *, headers, body, timeout_s):
        self.calls.append({"url": url, "body": dict(body)})
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


DECLARED = [
    mapper.FieldDecl(
        name="unit_price_amount",
        label="Unit price",
        synonyms=("price per unit", "unit cost", "Price/Unit"),
        unit="amount",
    ),
    mapper.FieldDecl(
        name="quantity_count",
        label="Quantity",
        synonyms=("qty", "number of units"),
        unit="count",
    ),
    mapper.FieldDecl(
        name="effective_from_date",
        label="Effective from",
        synonyms=("valid from", "start date"),
        unit=None,
    ),
]


def directory(**kwargs: Any) -> FakeDirectory:
    return FakeDirectory(DECLARED, **kwargs)


def reply(payload: Mapping[str, Any] | str) -> TransportReply:
    import json as _json

    content = payload if isinstance(payload, str) else _json.dumps(payload)
    return TransportReply(
        status=200,
        payload={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def seam_with(*replies: TransportReply) -> tuple[Seam, Any]:
    transport = ScriptedTransport(*replies) if replies else NeverCalledTransport()
    seam = Seam(
        provider=PROVIDERS["openai"],
        model="pinned-model-9",
        api_key="sk-test",
        prompt_version="map-v1",
        transport=transport,
        sleep=lambda _: None,
    )
    return seam, transport


# --- retrieval is pure --------------------------------------------------------


def test_an_exact_synonym_wins_outright():
    found = mapper.retrieve_candidates("Price/Unit", directory())
    assert found.candidates[0].target_field == "unit_price_amount"
    assert found.candidates[0].via == "exact-synonym"
    assert found.candidates[0].matched_on == "Price/Unit"
    assert found.resolves_without_a_model() is not None


def test_a_synonym_matches_through_punctuation_and_case():
    for written in ("price per unit", "PRICE PER UNIT", "Price Per Unit:", "price_per_unit"):
        found = mapper.retrieve_candidates(written, directory())
        settled = found.resolves_without_a_model()
        assert settled is not None, written
        assert settled.target_field == "unit_price_amount", written


def test_a_precedent_is_retrieved_and_keeps_the_analysts_authority():
    found = mapper.retrieve_candidates(
        "Charge per item", directory(precedents={"Charge per item": "unit_price_amount"})
    )
    precedent = [c for c in found.candidates if c.via == "precedent"]
    assert precedent and precedent[0].target_field == "unit_price_amount"

    result = mapper.propose_mapping(
        "Charge per item",
        directory(precedents={"Charge per item": "unit_price_amount"}),
        seam=seam_with()[0],
    )
    assert isinstance(result.outcome, Proposal)
    assert result.outcome.authority is Authority.ANALYST


def test_a_stale_precedent_naming_an_undeclared_field_is_ignored_not_obeyed():
    found = mapper.retrieve_candidates(
        "Charge per item", directory(precedents={"Charge per item": "field_removed_last_week"})
    )
    assert all(c.target_field != "field_removed_last_week" for c in found.candidates)
    assert "field_removed_last_week" not in found.allowed_fields


def test_a_fuzzy_match_is_offered_but_never_strong_enough_on_its_own():
    found = mapper.retrieve_candidates("number of units supplied", directory())
    assert found.candidates, "a near-miss label should still retrieve candidates"
    assert all(c.via == "fuzzy" for c in found.candidates)
    assert all(not c.strong for c in found.candidates)
    assert found.resolves_without_a_model() is None


def test_a_label_the_pack_knows_nothing_about_retrieves_nothing():
    found = mapper.retrieve_candidates("zzz unrelated column header zzz", directory())
    assert found.candidates == ()


def test_retrieval_is_deterministic():
    first = mapper.retrieve_candidates("unit cost", directory())
    second = mapper.retrieve_candidates("unit cost", directory())
    assert first == second


def test_two_institutions_different_words_land_on_one_field():
    """The whole requirement, as a single assertion."""
    one = mapper.retrieve_candidates("Price/Unit", directory()).resolves_without_a_model()
    two = mapper.retrieve_candidates(
        "Charge per item", directory(precedents={"Charge per item": "unit_price_amount"})
    ).resolves_without_a_model()
    assert one is not None and two is not None
    assert one.target_field == two.target_field == "unit_price_amount"


# --- no model call where none is permitted ------------------------------------


def test_an_exact_synonym_resolves_with_no_model_call():
    seam, transport = seam_with()
    result = mapper.propose_mapping("Price/Unit", directory(), seam=seam)

    assert transport.calls == [], "the transport was invoked; this must cost nothing"
    assert result.used_model is False
    assert seam.calls_made == 0
    assert isinstance(result.outcome, Proposal)
    assert result.outcome.target_field == "unit_price_amount"
    assert result.outcome.model == mapper.NO_MODEL
    assert result.outcome.prompt_version == prompts.NO_PROMPT
    assert "no model call" in result.outcome.reason


def test_one_strong_candidate_resolves_with_no_model_call():
    """Exactly one strong candidate is the no-model path, however many weak ones exist."""
    seam, transport = seam_with()
    result = mapper.propose_mapping(
        "valid from", directory(), seam=seam
    )
    strong = [c for c in result.candidates if c.strong]
    assert len(strong) == 1
    assert transport.calls == []
    assert result.used_model is False
    assert isinstance(result.outcome, Proposal)
    assert result.outcome.target_field == "effective_from_date"


def test_a_synonym_and_a_precedent_that_agree_are_certainty_not_ambiguity():
    seam, transport = seam_with()
    result = mapper.propose_mapping(
        "unit cost", directory(precedents={"unit cost": "unit_price_amount"}), seam=seam
    )
    assert transport.calls == []
    assert result.used_model is False
    assert isinstance(result.outcome, Proposal)
    assert result.outcome.target_field == "unit_price_amount"


def test_nothing_matched_is_a_deterministic_missing_not_a_provider_failure():
    seam, transport = seam_with()
    result = mapper.propose_mapping("zzz unrelated column header zzz", directory(), seam=seam)
    assert result.outcome is None
    assert result.used_model is False
    assert transport.calls == []
    assert "no model was called" in (result.missing_reason or "")


# --- the model arbitrates, from the list --------------------------------------


def test_a_genuinely_ambiguous_label_asks_the_model_and_gets_a_proposal():
    seam, transport = seam_with(
        reply(
            {
                "target_field": "quantity_count",
                "confidence": 0.82,
                "reason": "The sample value is a whole number of items, not an amount.",
            }
        )
    )
    result = mapper.propose_mapping(
        "Units / cost line",
        directory(),
        seam=seam,
        sample_value="14",
    )
    assert result.used_model is True
    assert len(transport.calls) == 1
    assert isinstance(result.outcome, Proposal)
    assert result.outcome.target_field == "quantity_count"
    assert result.outcome.confidence == 0.82
    assert result.outcome.model == "pinned-model-9"
    assert result.outcome.prompt_version == "map-v1"
    assert result.outcome.authority is Authority.MODEL
    assert result.outcome.reason.startswith("The sample value")


def test_the_request_constrains_the_choice_to_the_retrieved_list():
    seam, transport = seam_with(
        reply({"target_field": "quantity_count", "confidence": 0.7, "reason": "because."})
    )
    result = mapper.propose_mapping("Units / cost line", directory(), seam=seam)
    body = transport.calls[0]["body"]
    enum = body["response_format"]["json_schema"]["schema"]["properties"]["target_field"]["enum"]
    assert set(enum) == set(c.target_field for c in result.candidates)
    assert "field_the_pack_never_declared" not in enum
    # temperature 0 on this dialect, pinned model: the controlled variables, on the wire.
    assert body["temperature"] == 0.0
    assert body["model"] == "pinned-model-9"


def test_an_out_of_list_answer_is_rejected_retried_once_then_unavailable():
    """THE constraint. An invented field name is never accepted and never repaired."""
    seam, transport = seam_with(
        reply(
            {
                "target_field": "field_the_pack_never_declared",
                "confidence": 0.99,
                "reason": "It looked right to me.",
            }
        )
    )
    result = mapper.propose_mapping("Units / cost line", directory(), seam=seam)

    assert isinstance(result.outcome, Unavailable)
    assert result.outcome.reason == "non-conforming-reply"
    assert "field_the_pack_never_declared" in (result.outcome.detail or "")
    assert len(transport.calls) == 2, "one retry, then the review tray"
    # And nothing was quietly mapped to the closest declared field.
    assert not isinstance(result.outcome, Proposal)


def test_an_out_of_list_answer_followed_by_a_valid_one_is_accepted():
    seam, transport = seam_with(
        reply({"target_field": "made_up_field", "confidence": 0.9, "reason": "guess."}),
        reply({"target_field": "quantity_count", "confidence": 0.6, "reason": "whole number."}),
    )
    result = mapper.propose_mapping("Units / cost line", directory(), seam=seam)
    assert isinstance(result.outcome, Proposal)
    assert result.outcome.target_field == "quantity_count"
    assert len(transport.calls) == 2


def test_a_reply_with_no_reason_is_not_usable():
    """A mapping a reviewer cannot argue with is not a mapping we can ship."""
    seam, transport = seam_with(
        reply({"target_field": "quantity_count", "confidence": 0.9, "reason": "   "})
    )
    result = mapper.propose_mapping("Units / cost line", directory(), seam=seam)
    assert isinstance(result.outcome, Unavailable)
    assert result.outcome.reason == "non-conforming-reply"
    assert len(transport.calls) == 2


def test_prose_instead_of_the_schema_is_one_retry_then_the_tray():
    seam, transport = seam_with(reply("I would go with quantity_count here."))
    result = mapper.propose_mapping("Units / cost line", directory(), seam=seam)
    assert isinstance(result.outcome, Unavailable)
    assert result.outcome.reason == "non-conforming-reply"
    assert len(transport.calls) == 2


def test_a_provider_outage_mid_mapping_degrades_that_field_and_nothing_else():
    seam, _ = seam_with(TransportReply(status=503, text="upstream unavailable"))
    result = mapper.propose_mapping("Units / cost line", directory(), seam=seam)
    assert isinstance(result.outcome, Unavailable)
    assert result.outcome.reason == "provider-down"
    # The deterministic path is untouched by the outage: this is the degraded banner.
    settled = mapper.propose_mapping("Price/Unit", directory(), seam=seam)
    assert isinstance(settled.outcome, Proposal)
    assert settled.used_model is False


def test_an_ambiguous_label_with_no_model_configured_goes_to_the_tray_not_the_best_guess():
    result = mapper.propose_mapping("Units / cost line", directory(), seam=None)
    assert isinstance(result.outcome, Unavailable)
    assert result.outcome.reason == "no-key"
    assert len(result.candidates) > 1


# --- the fact-shaped entry point ----------------------------------------------


def test_one_fact_in_one_result_out_so_fan_out_stays_a_wrapper():
    fact = ExtractedFact(
        document_id="doc-1",
        source_label="Price/Unit",
        raw_value="12.50",
        raw_unit="amount",
        source_location={"type": "sheet", "sheet": "Sheet1", "cell": "B12"},
    )
    seam, transport = seam_with()
    result = mapper.propose_for_fact(fact, directory(), seam=seam)
    assert transport.calls == []
    assert isinstance(result.outcome, Proposal)
    assert result.outcome.source_label == "Price/Unit"


def test_the_fact_value_reaches_the_prompt_because_it_is_what_breaks_a_tie():
    fact = ExtractedFact(
        document_id="doc-1",
        source_label="Units / cost line",
        raw_value="14",
        source_location={"type": "text", "start": 0, "end": 3},
        context="A table of order lines.",
    )
    seam, transport = seam_with(
        reply({"target_field": "quantity_count", "confidence": 0.8, "reason": "whole number."})
    )
    mapper.propose_for_fact(fact, directory(), seam=seam, document_name="orders.csv")
    user_turn = transport.calls[0]["body"]["messages"][1]["content"]
    assert "'14'" in user_turn
    assert "orders.csv" in user_turn
    assert "A table of order lines." in user_turn
    assert "quantity_count" in user_turn


# --- the prompt contract ------------------------------------------------------


def test_the_prompt_version_is_explicit_because_a_round_report_controls_for_it():
    assert isinstance(prompts.PROMPT_VERSION, str) and prompts.PROMPT_VERSION
    assert prompts.NO_PROMPT != prompts.PROMPT_VERSION


def test_an_empty_candidate_list_is_never_offered_to_a_model():
    with pytest.raises(ValueError):
        prompts.mapping_choice_schema([])


def test_the_schema_closes_the_choice_and_forbids_extra_keys():
    schema = prompts.mapping_choice_schema(["a_field", "b_field", "a_field"])
    assert schema["properties"]["target_field"]["enum"] == ["a_field", "b_field"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"target_field", "confidence", "reason"}


def test_a_broken_directory_blocks_the_run_rather_than_mapping_nothing():
    """The one thing the mapper deliberately does not swallow.

    Every provider failure is a value, because a provider outage must degrade. A pack
    that cannot be read is the opposite case: CLAUDE.md section 6 says the run is blocked
    before any document is read, and silently retrieving zero candidates would instead
    mark every field `missing` and call it a result.
    """

    class BrokenDirectory:
        def fields(self):
            raise RuntimeError("the pack loader fell over")

        def precedent_for(self, source_label, *, tenant_id="demo"):
            return None

    with pytest.raises(RuntimeError):
        # Documented boundary: retrieval is pure and propagates a broken directory,
        # because a pack that cannot be read must block the run before any document is
        # read (CLAUDE.md section 6) rather than quietly mapping nothing.
        mapper.propose_mapping("Price/Unit", BrokenDirectory(), seam=None)
