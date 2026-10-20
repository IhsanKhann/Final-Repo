"""Narrative disclosures are ingestable, with offsets a reviewer can be shown.

"Narrative disclosures" is one of PS-12's five technical requirements and it had no adapter
at all: a real 5,894-byte disclosure returned zero facts. These tests pin what the adapter
promises (every figure, exact provenance, one record per sentence) and, just as importantly,
what it refuses to promise -- it does not decide what a figure means.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.adapters import ADAPTERS, extract_document
from backend.adapters.narrative import MEDIA_TYPES

GENERATED = Path(__file__).resolve().parents[1] / "eval" / "generated"
DISCLOSURE = GENERATED / "summit_trust_disclosure.txt"

SAMPLE = (
    "The account, for a term of 12 months, pays 3.416% annually on balances over $1,000. "
    "The yield is 3.547% and it takes effect July 1, 2026. "
    "A second account pays 1.25% with no minimum."
).encode("utf-8")


def test_the_narrative_media_type_is_dispatched():
    """The gap was this simple: text/plain was not in the table, so prose was unreadable."""
    for media_type in MEDIA_TYPES:
        assert media_type in ADAPTERS, f"{media_type} is not dispatched to any adapter"


def test_every_figure_in_a_sentence_is_found():
    result = extract_document(SAMPLE, "text/plain", document_id="d")
    assert result.status == "done", result.error
    values = {fact.raw_value for fact in result.facts}
    for expected in ("12", "3.416%", "$1,000", "3.547%", "1.25%"):
        assert expected in values, f"{expected} was not read out of the prose: {values}"


def test_every_offset_is_exactly_the_value_it_claims():
    """The whole point of provenance on prose: the reviewer is shown that span.

    An offset that does not round-trip is not provenance, so the adapter drops and counts
    it rather than reporting a span that highlights the wrong text.
    """
    source = SAMPLE.decode("utf-8")
    result = extract_document(SAMPLE, "text/plain", document_id="d")
    for fact in result.facts:
        location = fact.source_location
        assert location.type == "text"
        assert source[location.start : location.end] == fact.raw_value


def test_a_date_is_one_value_and_not_two_numbers():
    """Read as figures, "July 1, 2026" becomes "1" and "2026" -- two meaningless rows."""
    result = extract_document(SAMPLE, "text/plain", document_id="d")
    values = {fact.raw_value for fact in result.facts}
    assert "July 1, 2026" in values
    assert "2026" not in values, "the year leaked out of the date as its own figure"


def test_a_sentence_comma_is_not_swallowed_into_a_figure():
    """"$1,000." was being read as the figure "$1,000," which is not a number."""
    result = extract_document(SAMPLE, "text/plain", document_id="d")
    assert not [f for f in result.facts if f.raw_value.endswith(",")]


def test_each_sentence_is_its_own_record():
    """A disclosure describes a different product per sentence. One record per file would
    attach a figure to a product the sentence says nothing about."""
    result = extract_document(SAMPLE, "text/plain", document_id="d")
    records = {fact.record_key for fact in result.facts}
    assert len(records) == 3, f"three sentences, {len(records)} record(s): {records}"
    # The figures of one sentence must share its record.
    by_value = {f.raw_value: f.record_key for f in result.facts}
    assert by_value["3.416%"] == by_value["$1,000"]
    assert by_value["1.25%"] != by_value["3.416%"]


def test_a_candidate_label_is_offered_but_no_meaning_is_decided():
    """The adapter proposes words near the figure; it does not name a field.

    Deciding that "pays 3.416% annually" means a particular declared field is a judgement,
    and an adapter making it would be meaning living outside the pack (Law II).
    """
    result = extract_document(SAMPLE, "text/plain", document_id="d")
    labelled = [f for f in result.facts if f.source_label]
    assert labelled, "no candidate labels at all leaves the mapper nothing to arbitrate on"
    for fact in result.facts:
        # A label is words from the document, never a field name we invented.
        assert "_" not in fact.source_label, (
            f"{fact.source_label!r} looks like a declared field name, which this layer "
            "is not allowed to choose"
        )
        assert fact.context, "a figure with no sentence around it cannot be arbitrated"


def test_the_same_prose_reads_the_same_way_twice():
    first = extract_document(SAMPLE, "text/plain", document_id="d").facts
    second = extract_document(SAMPLE, "text/plain", document_id="d").facts
    assert [(f.raw_value, f.source_label, f.record_key) for f in first] == [
        (f.raw_value, f.source_label, f.record_key) for f in second
    ]


def test_a_label_does_not_change_with_grammar():
    """"for a term of 12" and "the term of 12" must give one candidate, not two.

    A label that varied with the article would make the precedent learned from one
    sentence useless for the next, which is the opposite of what precedents are for.
    """
    a = extract_document(b"The account, for a term of 12 months.", "text/plain").facts
    b = extract_document(b"The account, the term of 12 months.", "text/plain").facts
    assert a and b
    assert a[0].source_label == b[0].source_label


def test_a_file_that_is_not_utf8_is_an_error_not_a_shifted_offset():
    """Replacing bad bytes would move every offset after the first one.

    A wrong offset is worse than no offset: it highlights the wrong sentence and the
    evidence panel confidently shows text the number did not come from.
    """
    result = extract_document(b"rate is 1.5%\xff\xfe and more", "text/plain", document_id="d")
    assert result.status == "error"
    assert result.facts == []
    assert "codec" in (result.error or "").lower() or "utf" in (result.error or "").lower()


def test_prose_with_no_figures_is_a_document_with_nothing_in_it_not_a_failure():
    result = extract_document(b"This page describes our terms in words only.", "text/plain")
    assert result.status == "done"
    assert result.facts == []


def test_the_real_disclosure_is_now_ingestable():
    """The measured gap: this file returned 0 facts and could not be ingested at all."""
    if not DISCLOSURE.is_file():
        pytest.skip("generated disclosure absent; run python -m backend.eval.make_documents")

    source = DISCLOSURE.read_text(encoding="utf-8")
    result = extract_document(DISCLOSURE.read_bytes(), "text/plain", document_id="summit")
    assert result.status == "done"
    assert len(result.facts) > 50, f"only {len(result.facts)} figures found in a disclosure"
    assert len({f.record_key for f in result.facts}) > 1
    for fact in result.facts:
        location = fact.source_location
        assert source[location.start : location.end] == fact.raw_value
