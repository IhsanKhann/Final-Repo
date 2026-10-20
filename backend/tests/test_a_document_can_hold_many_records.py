"""A document is not a record, and the gold table has to say so.

This exists because the dataset was 30x short and nothing caught it. Pacific Savings' sheet
holds 30 product rows; every one of them is a record with its own rate, term and minimum
deposit. Keyed on the document alone, the gold table showed one row per file and the last
value written won -- so PS-12's "standardized, validated dataset" was a thirtieth of the
data, and the golden set could never have matched against it.

Three things had to agree for that to be fixed, and all three are pinned here: the adapters
have to emit a record key, the grouping has to use it, and the ledger has to version on it
WITHOUT losing the ability to version a genuine re-run of the same cell.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.engine.ledger import LedgerEntry, SqliteLedger

GENERATED = Path(__file__).resolve().parents[1] / "eval" / "generated"

#: Every adapter that reads a tabular document, with a generated file to read.
TABULAR_CASES = (
    ("pacific_savings_rates.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("first_national_bank_rates.pdf", "application/pdf"),
    ("heritage_financial_rates.html", "text/html"),
)


@pytest.mark.parametrize("name,media_type", TABULAR_CASES)
def test_every_adapter_gives_each_fact_a_record_key(name, media_type):
    """An adapter that forgot would silently collapse the document back to one record."""
    path = GENERATED / name
    if not path.is_file():
        pytest.skip(f"{name} absent; run python -m backend.eval.make_documents")

    from backend.adapters import extract_document

    result = extract_document(path.read_bytes(), media_type, document_id=name)
    assert result.status == "done", result.error
    assert result.facts, "no facts, so this proves nothing about their keys"

    unkeyed = [fact for fact in result.facts if not fact.record_key]
    assert not unkeyed, (
        f"{len(unkeyed)} fact(s) from {name} carry no record_key, so every record in this "
        "document would collapse into one row"
    )


@pytest.mark.parametrize("name,media_type", TABULAR_CASES)
def test_a_tabular_document_yields_more_than_one_record(name, media_type):
    """The actual bug: these documents hold many records and we reported one."""
    path = GENERATED / name
    if not path.is_file():
        pytest.skip(f"{name} absent; run python -m backend.eval.make_documents")

    from backend.adapters import extract_document

    result = extract_document(path.read_bytes(), media_type, document_id=name)
    records = {fact.record_key for fact in result.facts}
    assert len(records) > 1, (
        f"{name} produced {len(records)} record(s); a rate sheet holds one per product row"
    )


def test_the_record_key_is_deterministic():
    """Same bytes in, same keys out. A key that moved would break re-run comparison."""
    name, media_type = TABULAR_CASES[0]
    path = GENERATED / name
    if not path.is_file():
        pytest.skip(f"{name} absent")

    from backend.adapters import extract_document

    data = path.read_bytes()
    first = [f.record_key for f in extract_document(data, media_type, document_id="d").facts]
    second = [f.record_key for f in extract_document(data, media_type, document_id="d").facts]
    assert first == second


# --- the ledger's two halves -------------------------------------------------


def _entry(record_key: str, field: str, value: str, run: str) -> LedgerEntry:
    return LedgerEntry(
        run_id=run,
        document_id="doc-1",
        mapping_id=f"map-{record_key}-{field}",
        record_key=record_key,
        source_label="a label",
        target_field=field,
        raw_value="1",
        value=value,
        status="auto",
        confidence=0.95,
    )


def test_sibling_records_are_separate_cells_not_versions_of_one(tmp_path):
    """Thirty rows of one sheet are thirty cells. Keyed on the field alone they read as
    version 30 of a single value, which hid 29 records AND made the audit trail claim a
    cell had been revised thirty times."""
    ledger = SqliteLedger(tmp_path / "ledger.db")
    versions = [
        ledger.append(_entry(f"row:{row}", "f_rate", f"{row}.0", "run-1")).version
        for row in range(1, 31)
    ]
    assert versions == [1] * 30, (
        "sibling records were versioned as revisions of each other: " f"{versions}"
    )


def test_a_genuine_rerun_of_the_same_cell_still_versions(tmp_path):
    """The other half, and the one a naive fix breaks: replay is the audit claim.

    If adding the record key had stopped re-runs from versioning, the sibling test above
    would pass and the ledger would silently stop recording history.
    """
    ledger = SqliteLedger(tmp_path / "ledger.db")
    first = ledger.append(_entry("row:7", "f_rate", "1.0", "run-1"))
    second = ledger.append(_entry("row:7", "f_rate", "1.5", "run-2"))
    sibling = ledger.append(_entry("row:8", "f_rate", "9.9", "run-2"))

    assert (first.version, second.version) == (1, 2), "the same cell did not version"
    assert sibling.version == 1, "a sibling row was versioned as a revision"

    history = ledger.history("doc-1", "f_rate")
    assert [e.value for e in history if e.record_key == "row:7"] == ["1.0", "1.5"]


def test_the_current_state_of_a_document_is_one_row_per_record_and_field(tmp_path):
    ledger = SqliteLedger(tmp_path / "ledger.db")
    for row in (1, 2, 3):
        for field in ("f_rate", "f_yield"):
            ledger.append(_entry(f"row:{row}", field, "1.0", "run-1"))
    # A re-run of one cell must not add a row to the current state, only a version.
    ledger.append(_entry("row:2", "f_rate", "2.0", "run-2"))

    latest = ledger.latest_for_document("doc-1")
    assert len(latest) == 6, f"expected 3 records x 2 fields, got {len(latest)}"
    revised = [e for e in latest if e.record_key == "row:2" and e.target_field == "f_rate"]
    assert len(revised) == 1 and revised[0].value == "2.0"


def test_the_chain_still_verifies_across_records_and_reruns(tmp_path):
    ledger = SqliteLedger(tmp_path / "ledger.db")
    for row in range(1, 6):
        ledger.append(_entry(f"row:{row}", "f_rate", "1.0", "run-1"))
    ledger.append(_entry("row:3", "f_rate", "2.0", "run-2"))
    ok, broken = ledger.verify_chain()
    assert ok, f"hash chain broken at {broken}"
