"""A confirmed golden row and the real mapping of the same value must find each other.

This exists because the scorer's match key could not match anything, and nothing was red.
The golden side named `first_national_bank_rates_page1.pdf` -- an upstream rate sheet that
is on no disk -- and the produced side named `doc-ab12cd34ef56`, a uuid minted at ingest.
Two key spaces that cannot intersect, so a fully confirmed golden set would have published
`mapping_accuracy: 0.0, matched: 0, unmatched: 30` while the pipeline was mapping
correctly, and `score.py` counts an unmatched CONFIRMED row as wrong rather than as
missing. A zero that reads as catastrophic failure is the worst shape a broken join can
take, because the obvious response is to go looking at the mapper.

The second half was quieter and worse. With the document identifier fixed,
(document, heading) is unique on the golden side and many-to-one on the produced side:
First National's one sheet holds 26 records, each with its own "Rate". All 26 resolve to
the same field, so `mapping_accuracy` would have looked healthy while
`conversion_correctness` compared the golden row's expected value against whichever of 26
different rates happened to be first -- a coin flip wearing the name of the one criterion
the x12 monthly case exists to prove. So these tests pin the record dimension too: one
heading on thirty records must not collapse to one row, and a key that cannot tell
candidates apart must REFUSE rather than pick.

What they deliberately do not do: write to golden_set.csv, or put initials in
`confirmed_by`. Two named humans own that column. Confirmation here is stamped on an
in-memory copy, which asserts nothing about the labels and leaves the shipped file
unconfirmed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="fastapi is not importable in this environment")

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import deps  # noqa: E402
from backend.api.main import create_app  # noqa: E402
from backend.engine.config import SECRETS  # noqa: E402
from backend.engine.contracts import Mapping, SourceLocationSheet  # noqa: E402
from backend.eval.score import (  # noqa: E402
    GoldenRow,
    Score,
    canonical_value,
    default_mapping_key,
    load_golden_set,
    mapping_key_for,
    score,
)

GENERATED = Path(__file__).resolve().parents[1] / "eval" / "generated"

#: Two of the six, chosen rather than sampled: the xlsx is the only document that quotes a
#: monthly rate, so it is the only one that exercises the conversion criterion, and the
#: text PDF is the control. Uploading all six would measure the same join four more times.
SUBSET = ("pacific_savings_rates.xlsx", "first_national_bank_rates.pdf")

#: Said out loud in the fixture rather than hidden in a helper: this is not an attestation.
IN_MEMORY_ONLY = "not a confirmation: stamped in a test, the shipped file stays unconfirmed"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """A real client with the honest service and deliberately no key.

    Scrubbing the keys is not tidiness: with one present this test would make live,
    billable model calls on every ambiguous label.
    """
    for env_var in SECRETS.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / "config.db"))
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("LEDGER_DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.delenv("PIPELINE", raising=False)
    monkeypatch.delenv("USE_FIXTURES", raising=False)
    deps.reset_wiring()
    try:
        yield TestClient(create_app())
    finally:
        deps.reset_wiring()


@pytest.fixture
def real_run(client: TestClient):
    """Upload the subset, and hand back what a scorer gets: mappings and document names."""
    paths = [GENERATED / name for name in SUBSET]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        pytest.skip(
            f"generated fixtures absent ({missing}); run python -m backend.eval.make_documents"
        )
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    response = client.post("/api/batches", data={"pack_id": "banking_rates"}, files=files)
    assert response.status_code == 201, response.text
    assert response.json()["stage"] == "ready", response.json()

    # The document NAME is the half of the key a Mapping does not carry, and the
    # repository is where the production call site reads it from too.
    repo = deps.get_repository()
    names = {
        document.id: document.name
        for batch in repo.list_batches(tenant_id="demo")
        for document in repo.list_documents(batch.id, tenant_id="demo")
    }
    mappings = repo.list_mappings(tenant_id="demo")
    assert mappings, "the run produced no mappings at all, so this proves nothing"
    return mappings, names


def _confirmed(rows: list[GoldenRow]) -> list[GoldenRow]:
    return [row.model_copy(update={"confirmed_by": IN_MEMORY_ONLY}) for row in rows]


def _row(gold_id: str, **overrides) -> GoldenRow:
    data = dict(
        gold_id=gold_id,
        institution_name="an institution",
        document_file="a_document.pdf",
        document_format="pdf_text",
        product_type="a product",
        source_label="a label",
        value_as_printed="1.0",
        expected_field="f_annual",
        expected_value="1.0",
        expected_unit="u_year",
        conversion_expected="none",
        difficulty="the easy case",
        confirmed_by=IN_MEMORY_ONLY,
    )
    data.update(overrides)
    return GoldenRow(**data)


def _mapping(
    row: GoldenRow,
    *,
    mapping_id: str | None = None,
    field: str | None = None,
    raw: str | None = None,
    value: str | None = None,
    unit: str | None = None,
) -> Mapping:
    return Mapping(
        id=mapping_id or f"m-{row.gold_id}",
        document_id=row.document_file,
        source_label=row.source_label,
        target_field=field if field is not None else row.expected_field,
        raw_value=raw if raw is not None else row.value_as_printed,
        value=value if value is not None else row.expected_value,
        unit=unit if unit is not None else row.expected_unit,
        confidence=0.95,
        status="auto",
        source_location=SourceLocationSheet(sheet="S", cell="A1"),
    )


# --- the test that would have caught it --------------------------------------


def test_a_confirmed_golden_row_matches_the_real_mapping_of_the_same_value(real_run):
    """The headline. A real run, no API key, and the join has to land on real mappings."""
    mappings, names = real_run
    rows = _confirmed(load_golden_set())

    result = score(mappings, rows, document_names=names)
    assert isinstance(result, Score), result

    uploaded = {name.casefold() for name in SUBSET}
    expected_rows = [row for row in rows if row.document_file.casefold() in uploaded]
    assert len(expected_rows) == 10, "the golden set should hold five rows per institution"

    landed = [
        outcome
        for outcome in result.outcomes
        if outcome.gold_id in {row.gold_id for row in expected_rows} and outcome.candidates
    ]
    assert landed, (
        "not one golden row found a mapping in a run that produced "
        f"{len(mappings)} of them -- the match key joins two key spaces that cannot "
        "intersect, which is the defect this test exists for"
    )
    assert result.matched >= len(landed) > 0
    assert result.mapping_accuracy > 0.0, "a real run scored exactly zero, which is the bug"
    assert any(outcome.field_correct for outcome in landed)


def test_the_conversion_row_is_measured_against_one_record_and_not_a_coin_flip(real_run):
    """The x12 case is the whole conversion criterion, so its join must be exact.

    `Nominal (monthly)` appears on all thirty of Pacific's product rows. Keyed on the
    heading alone this row would have been scored against an arbitrary one of them; keyed
    on the printed value as well, it resolves to a single mapping and the recovered annual
    figure is a measurement.
    """
    mappings, names = real_run
    rows = _confirmed(load_golden_set())
    conversion = [
        row
        for row in rows
        if row.document_file.casefold() == "pacific_savings_rates.xlsx" and row.needs_conversion
    ]
    assert len(conversion) == 1, f"expected one monthly row to exist, got {len(conversion)}"

    result = score(mappings, rows, document_names=names)
    assert isinstance(result, Score)
    outcome = next(o for o in result.outcomes if o.gold_id == conversion[0].gold_id)

    assert outcome.candidates == 1, (
        "the monthly rate matched "
        f"{outcome.candidates} mappings, so conversion_correctness would be scored against "
        "whichever record came first"
    )
    assert outcome.conversion_was_expected is True
    assert outcome.field_correct is True, outcome
    assert outcome.value_correct is True, outcome
    assert result.conversion_rows >= 1
    assert result.conversion_correctness > 0.0


def test_one_heading_on_thirty_records_does_not_collapse_to_one_row(real_run):
    """The second defect, measured: (document, heading) is not a key on the produced side."""
    mappings, names = real_run
    key = mapping_key_for(names)
    by_document_and_label: dict[tuple[str, str], set[str]] = {}
    for mapping in mappings:
        document, label, _value = key(mapping)
        by_document_and_label.setdefault((document, label), set()).add(mapping.record_key)

    worst = max(by_document_and_label.values(), key=len)
    assert len(worst) > 1, (
        "no heading in this run covered more than one record, so the corpus no longer "
        "exercises the record dimension and this suite has stopped protecting it"
    )
    # And with the value in the key, the same heading resolves to far fewer candidates.
    widest = max(len(v) for v in by_document_and_label.values())
    keyed = {}
    for mapping in mappings:
        keyed.setdefault(key(mapping), []).append(mapping)
    assert max(len(v) for v in keyed.values()) < widest


# --- the refusal, which is what replaces a guess ------------------------------


def test_candidates_a_key_cannot_tell_apart_are_refused_rather_than_scored():
    """A scorer that silently picks one of several is the thing being prevented."""
    rows = [_row(f"G{i:03d}") for i in range(30)]
    target = rows[0]
    produced = [
        _mapping(target, mapping_id="m-a", value="1.0"),
        _mapping(target, mapping_id="m-b", value="9.9"),  # same key, different answer
    ] + [_mapping(row) for row in rows[1:]]

    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.ambiguous == 1
    assert result.matched == 29
    assert result.unmatched == 1, "a refused row must still count against the denominator"
    assert result.mapping_accuracy == round(29 / 30, 4)

    outcome = next(o for o in result.outcomes if o.gold_id == target.gold_id)
    assert outcome.field_correct is False
    assert outcome.produced_field is None
    assert outcome.candidates == 2
    assert "refused" in (outcome.note or "")
    assert "which record" in (outcome.note or "")


def test_a_refused_conversion_row_is_counted_wrong_and_not_dropped():
    """Refusing must not shrink the conversion denominator, or accuracy would rise."""
    rows = [_row("G001", conversion_expected="x12", expected_value="4.0596")] + [
        _row(f"G{i:03d}") for i in range(2, 31)
    ]
    produced = [
        _mapping(rows[0], mapping_id="m-a", value="4.0596"),
        _mapping(rows[0], mapping_id="m-b", value="2.0"),
    ] + [_mapping(row) for row in rows[1:]]

    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.ambiguous == 1
    assert result.conversion_rows == 1
    assert result.conversion_correctness == 0.0


def test_candidates_that_all_say_the_same_thing_are_not_a_choice():
    """The other half, and the one an over-strict fix breaks.

    Thirty records can share a heading and a printed value legitimately -- a zero term, a
    thousand-dollar minimum. Where every candidate agrees on the field, the value and the
    unit, there is nothing left for the scorer to get wrong, and refusing would make a
    correct run unscoreable.
    """
    rows = [_row(f"G{i:03d}") for i in range(30)]
    produced = [_mapping(rows[0], mapping_id=f"m-{n}") for n in range(30)] + [
        _mapping(row) for row in rows[1:]
    ]

    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.ambiguous == 0
    assert result.matched == 30
    assert result.mapping_accuracy == 1.0
    outcome = next(o for o in result.outcomes if o.gold_id == rows[0].gold_id)
    assert outcome.candidates == 30, "the join's precision must be visible, not implied"


# --- the normalisation, stated rather than incidental -------------------------


def test_the_join_uses_the_generated_filename_and_never_the_upstream_one():
    """ps06's own filename is provenance. Nothing by that name is ever ingested."""
    row = _row(
        "G001",
        document_file="pacific_savings_rates.xlsx",
        ps06_source_file="pacific_savings_rates_page3.pdf",
    )
    rows = [row] + [_row(f"G{i:03d}") for i in range(2, 31)]
    mapping = _mapping(row).model_copy(update={"document_id": "doc-ab12cd34ef56"})

    names = {"doc-ab12cd34ef56": "pacific_savings_rates.xlsx"}
    result = score([mapping] + [_mapping(r) for r in rows[1:]], rows, document_names=names)
    assert isinstance(result, Score)
    assert next(o for o in result.outcomes if o.gold_id == "G001").field_correct is True

    # The same run against the upstream name matches nothing, which is the original bug.
    stale = {"doc-ab12cd34ef56": "pacific_savings_rates_page3.pdf"}
    refused = score([mapping] + [_mapping(r) for r in rows[1:]], rows, document_names=stale)
    assert isinstance(refused, Score)
    assert next(o for o in refused.outcomes if o.gold_id == "G001").candidates == 0


def test_every_document_the_golden_set_names_is_one_the_generator_wrote():
    """The join is only as good as the filename, so the filename is checked, not assumed."""
    if not GENERATED.is_dir():
        pytest.skip("generated fixtures absent; run python -m backend.eval.make_documents")
    on_disk = {path.name for path in GENERATED.iterdir() if path.is_file()}
    rows = load_golden_set()
    for row in rows:
        assert row.document_file in on_disk, (
            f"{row.gold_id} keys on {row.document_file!r}, which the generator never "
            "wrote -- every key for that institution will miss"
        )
        assert row.ps06_source_file not in on_disk, (
            f"{row.gold_id}'s upstream name {row.ps06_source_file!r} now exists on disk, "
            "so the two columns no longer mean different things and the join is ambiguous"
        )


def test_a_value_printed_in_another_house_style_keys_to_the_same_record():
    """Each institution prints its own way; the key has to see through that, once."""
    assert canonical_value("$1,000") == canonical_value("1000") == "1000"
    assert canonical_value("1.36 %") == canonical_value("1.36")
    assert canonical_value("01 Aug 2026") == canonical_value("2026-08-01") == "2026-08-01"
    assert canonical_value("July 1, 2026") == "2026-07-01"
    assert canonical_value(None) == canonical_value("  ") == ""


def test_an_august_date_is_not_keyed_as_a_one_month_term():
    """The trap under the canonicaliser: parse_numeric("01 Aug 2026") is 1.

    A number-first key would file every day-first date under the term that shares its day
    number, and then match a date row against a term mapping -- a plausible number from
    the wrong record, which is the failure mode worth more than any coverage.
    """
    from backend.engine.units import parse_numeric

    assert parse_numeric("01 Aug 2026") == 1, "the trap has moved; this test now proves nothing"
    assert canonical_value("01 Aug 2026") != canonical_value("1")


def test_two_different_days_are_never_scored_as_the_same_value():
    """The same trap on the value comparison: 01 Aug and 01 Sep both read as 1."""
    rows = [
        _row(
            "G001",
            conversion_expected="date",
            value_as_printed="2026-08-01",
            expected_value="01 Aug 2026",
            expected_unit="",
        )
    ] + [_row(f"G{i:03d}") for i in range(2, 31)]
    produced = [_mapping(rows[0], value="01 Sep 2026", unit="")] + [
        _mapping(row) for row in rows[1:]
    ]
    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.conversion_rows == 1
    assert result.conversion_correctness == 0.0, "two different days were scored as one"


def test_a_document_the_scorer_has_no_name_for_matches_nothing_and_does_not_raise():
    """An unresolvable document is a gap in the measurement, not an exception."""
    rows = [_row(f"G{i:03d}") for i in range(30)]
    orphan = _mapping(rows[0]).model_copy(update={"document_id": "doc-nobody-knows"})
    result = score([orphan], rows, document_names={})
    assert isinstance(result, Score)
    assert result.matched == 0
    assert result.unmatched == 30
    assert result.ambiguous == 0
    assert default_mapping_key(orphan)[0] == "doc-nobody-knows"


def test_naming_the_documents_and_the_key_at_once_is_refused():
    """One of the two would have to be ignored, and a silently ignored argument is a bug."""
    rows = [_row(f"G{i:03d}") for i in range(30)]
    with pytest.raises(ValueError, match="not both"):
        score([], rows, document_names={}, mapping_key=default_mapping_key)


def test_the_refusal_below_thirty_confirmed_rows_survives_a_working_join(real_run):
    """The point of the whole module: a working key must not make it scoreable."""
    mappings, names = real_run
    result = score(mappings, document_names=names)
    assert result.scoreable is False
    assert not hasattr(result, "mapping_accuracy")
    assert result.confirmed == 0, (
        "someone has put initials in confirmed_by; only the two named humans may, and "
        "this suite must not be what discovers it"
    )
