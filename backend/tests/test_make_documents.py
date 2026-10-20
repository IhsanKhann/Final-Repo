"""What these tests protect: the fixtures cannot drift, and they cannot disagree with the
golden set.

Two different failures are being guarded here. The first is drift: the demo is rehearsed
against these six documents, so a generator that emits different bytes on Tuesday has
invalidated every number anyone quoted on Monday. The second is a silent disagreement with
`eval/golden_set.csv`, which was built from the same terminology table -- if a heading is
spelled one way in a document and another way in the answer key, accuracy is measured
against documents nobody generated, and nothing goes red.
"""

from __future__ import annotations

import csv as csv_module
import hashlib
import json
from pathlib import Path

import fitz
import pytest

from backend.eval import make_documents
from backend.eval.make_golden_set import PROPOSED_FIELD, REPORTING_STYLE

GOLDEN_SET = Path(make_documents.__file__).resolve().parent / "golden_set.csv"


def _hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> tuple[Path, dict]:
    out = tmp_path_factory.mktemp("generated")
    truth = make_documents.generate(out_dir=out)
    return out, truth


def _document(truth: dict, institution: str) -> dict:
    for entry in truth["documents"]:
        if entry["institution"] == institution:
            return entry
    raise AssertionError(f"{institution} produced no document")


def test_the_same_csv_produces_byte_identical_documents_twice(tmp_path):
    first, second = tmp_path / "run-1", tmp_path / "run-2"
    make_documents.generate(out_dir=first)
    make_documents.generate(out_dir=second)

    left, right = _hashes(first), _hashes(second)
    assert left == right, "the generator is not deterministic: the demo can drift"
    assert len(left) == 7, f"expected six documents and one sidecar, got {sorted(left)}"


def test_the_sidecar_hash_describes_the_file_beside_it(generated):
    out, truth = generated
    for entry in truth["documents"]:
        payload = (out / entry["file"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        assert len(payload) == entry["size_bytes"]


def test_every_institution_is_rendered_in_the_format_the_golden_set_declares(generated):
    _, truth = generated
    rendered = {entry["institution"]: entry["format"] for entry in truth["documents"]}
    declared = {name: style["format"] for name, style in REPORTING_STYLE.items()}
    assert rendered == declared


def test_every_golden_set_label_is_a_label_the_documents_actually_use(generated):
    """The one test that catches the generator and the answer key drifting apart."""
    _, truth = generated
    written = {entry["institution"]: entry["header_map"] for entry in truth["documents"]}
    with GOLDEN_SET.open(encoding="utf-8", newline="") as handle:
        rows = list(csv_module.DictReader(handle))
    assert rows, "golden_set.csv is empty, so this test proves nothing"
    for row in rows:
        labels = written[row["institution_name"]]
        label = row["source_label"]
        assert label in labels, (
            f"golden row {row['gold_id']} scores the label {label!r} for "
            f"{row['institution_name']}, which that document does not use: {sorted(labels)}"
        )
        assert labels[label] == row["expected_field"]


def test_each_source_row_reaches_exactly_one_document(generated):
    _, truth = generated
    seen: list[int] = []
    for entry in truth["documents"]:
        seen.extend(row["csv_index"] for row in entry["rows"])
    assert len(seen) == truth["source_row_count"]
    assert sorted(seen) == list(range(truth["source_row_count"])), "a row was lost or doubled"


def test_the_scanned_document_has_no_text_layer(generated):
    out, truth = generated
    entry = _document(truth, "Metro Credit Union")
    document = fitz.open(out / entry["file"])
    try:
        assert document.page_count > 0
        for page in document:
            assert page.get_text().strip() == "", (
                "the scanned fixture kept a text layer, so it does not exercise the scan "
                "path at all"
            )
    finally:
        document.close()


def test_the_text_pdf_keeps_the_text_layer_the_scan_gave_up(generated):
    out, truth = generated
    entry = _document(truth, "First National Bank")
    document = fitz.open(out / entry["file"])
    try:
        text = "\n".join(page.get_text() for page in document)
    finally:
        document.close()
    first = entry["rows"][0]
    assert first["as_written"]["Rate"] in text


def test_the_monthly_quote_takes_twelve_to_become_the_annual_truth(generated):
    _, truth = generated
    entry = _document(truth, "Pacific Savings")
    assert REPORTING_STYLE["Pacific Savings"]["rate_is_monthly"] is True
    for row in entry["rows"]:
        monthly = row["nominal_monthly_pct"]
        annual = row["interest_rate_annual_pct"]
        if annual > 0:
            assert monthly < annual, "a monthly quote that is not smaller proves nothing"
        assert row["recovered_annual_pct"] == pytest.approx(monthly * 12, abs=1e-6)
        # The document prints four decimals because the golden set says it does. The
        # printed figure is therefore off by at most 0.00005, so x12 recovers the annual
        # rate to within 12 x 0.00005 = 0.0006 of a percentage point, plus float slack --
        # never exactly, which is why a scorer has to compare numerically and why the bound
        # is asserted here rather than left for someone to meet with a strict equality.
        assert row["recovered_annual_pct"] == pytest.approx(annual, abs=6.1e-4)


def test_the_monthly_figure_is_what_the_golden_set_says_is_printed(generated):
    _, truth = generated
    entry = _document(truth, "Pacific Savings")
    printed = {
        row["csv_index"]: row["as_written"][REPORTING_STYLE["Pacific Savings"]["labels"]["rate_pct"]]
        for row in entry["rows"]
    }
    with GOLDEN_SET.open(encoding="utf-8", newline="") as handle:
        golden = [
            row
            for row in csv_module.DictReader(handle)
            if row["institution_name"] == "Pacific Savings"
            and row["conversion_expected"] != "none"
        ]
    assert golden, "no monthly-conversion row in the golden set to check against"
    for row in golden:
        assert row["value_as_printed"] in printed.values(), (
            f"golden row {row['gold_id']} expects the sheet to print "
            f"{row['value_as_printed']!r}, which it does not"
        )


def test_the_footnote_contradicts_the_table_it_sits_under(generated):
    out, truth = generated
    entry = _document(truth, "Valley Community Bank")
    flagged = [row for row in entry["rows"] if row["ambiguous"]]
    assert flagged, "the ambiguity case generated no ambiguity"

    document = fitz.open(out / entry["file"])
    try:
        pages = [page.get_text() for page in document]
    finally:
        document.close()

    for row in flagged:
        clash = row["footnote_contradiction"]
        table_value = clash["table_interest_rate_annual_pct"]
        footnote_value = clash["footnote_interest_rate_annual_pct"]
        assert footnote_value != table_value
        text = pages[clash["page"] - 1]
        assert str(table_value) in text
        assert str(footnote_value) in text, (
            "the contradicting figure is recorded in the ground truth but is not on the page"
        )


def test_the_narrative_document_has_no_table_to_parse(generated):
    out, truth = generated
    entry = _document(truth, "Summit Trust")
    text = (out / entry["file"]).read_text(encoding="utf-8")
    assert "<table" not in text and "\t" not in text
    labels = REPORTING_STYLE["Summit Trust"]["labels"]
    assert labels["apy_pct"] in text
    assert labels["min_deposit"] in text
    first = entry["rows"][0]
    assert first["as_written"][labels["apy_pct"]] in text


def test_the_html_document_spells_its_values_with_a_space_before_the_percent(generated):
    out, truth = generated
    entry = _document(truth, "Heritage Financial")
    text = (out / entry["file"]).read_text(encoding="utf-8")
    label = REPORTING_STYLE["Heritage Financial"]["labels"]["rate_pct"]
    assert f"<th>{label}</th>" in text
    written = entry["rows"][0]["as_written"][label]
    assert written.endswith(" %"), f"expected '1.36 %' formatting, got {written!r}"
    assert f"<td>{written}</td>" in text


def test_every_canonical_field_in_the_sidecar_is_one_the_golden_set_declares(generated):
    _, truth = generated
    allowed = set(PROPOSED_FIELD.values()) | {"product_type"}
    for entry in truth["documents"]:
        assert set(entry["header_map"].values()) <= allowed, (
            "the sidecar names a field the answer key does not declare"
        )


def test_the_sidecar_is_stable_text_a_diff_can_be_read(generated):
    out, _ = generated
    raw = (out / "ground_truth.json").read_text(encoding="utf-8")
    assert raw.endswith("\n")
    reparsed = json.loads(raw)
    assert json.dumps(reparsed, indent=2, sort_keys=True, ensure_ascii=True) + "\n" == raw
