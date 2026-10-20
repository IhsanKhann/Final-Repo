"""What these tests protect: provenance is real, and one bad file cannot end a run.

The claims under test are the ones made on stage. A bbox is normalized 0-1 because it was
divided in the adapter -- so a fact carrying absolute points must be unconstructible, not
merely unlikely. A cell reference and a character offset must actually select the value they
claim, because "click the cell" is the answer to "how do you know it didn't hallucinate".
A scanned page with no vision backend must come back `unavailable` rather than empty, since
an empty result is indistinguishable from a page that genuinely had nothing on it. And a
corrupt file of every format must leave the batch running.

The fixtures are generated here rather than read from `eval/generated/`, so these tests fail
when the generator breaks instead of passing against a stale artifact.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.adapters import ADAPTERS, csv as csv_adapter, html as html_adapter
from backend.adapters import extract_document as dispatch
from backend.adapters import pdf_scan, pdf_text, sheet
from backend.adapters.base import cell_ref, column_letter, normalized_bbox
from backend.engine.contracts import (
    SourceLocationPdf,
    SourceLocationSheet,
    SourceLocationText,
    Unavailable,
)
from backend.eval import make_documents

REPO_ROOT = Path(make_documents.__file__).resolve().parents[2]
PS06 = REPO_ROOT / "data" / "samples" / "ps06_sample_rate_sheets.csv"
ADAPTER_PACKAGE = REPO_ROOT / "backend" / "adapters"

XLSX = sheet.XLSX_MEDIA_TYPE
PDF = "application/pdf"


@pytest.fixture(scope="module")
def documents(tmp_path_factory) -> dict[str, tuple[bytes, str]]:
    """institution -> (bytes, media type), straight from the generator."""
    out = tmp_path_factory.mktemp("adapter-fixtures")
    truth = make_documents.generate(out_dir=out)
    return {
        entry["institution"]: ((out / entry["file"]).read_bytes(), entry["media_type"])
        for entry in truth["documents"]
    }


@pytest.fixture(scope="module")
def ground_truth(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("adapter-truth")
    return make_documents.generate(out_dir=out)


def _entry(truth: dict, institution: str) -> dict:
    return next(e for e in truth["documents"] if e["institution"] == institution)


# --- the plumbing the rest of the package leans on ----------------------------


def test_a_cell_reference_counts_columns_the_way_a_spreadsheet_does():
    assert column_letter(0) == "A"
    assert column_letter(25) == "Z"
    assert column_letter(26) == "AA"
    assert cell_ref(1, 12) == "B12"


def test_absolute_points_cannot_survive_as_a_bounding_box():
    """The guard that makes the contract's 0-1 rule enforceable rather than aspirational."""
    with pytest.raises(ValueError):
        SourceLocationPdf(page=1, bbox=(72.0, 100.0, 120.0, 14.0))
    with pytest.raises(ValueError):
        # Dividing by the wrong page: a landscape width against a portrait page.
        normalized_bbox(500.0, 100.0, 560.0, 114.0, 200.0, 842.0)


def test_the_division_turns_two_corners_into_an_origin_and_a_size():
    box = normalized_bbox(59.5, 84.2, 119.0, 126.3, 595.0, 842.0)
    assert box == pytest.approx((0.1, 0.1, 0.1, 0.05), abs=1e-3)


# --- one of each format produces facts with provenance ------------------------


def test_the_csv_adapter_addresses_values_as_spreadsheet_cells():
    result = csv_adapter.extract_document(PS06.read_bytes(), document_id="ps06")
    assert result.status == "done"
    assert result.engine in {"pandas", "stdlib-csv"}
    assert len(result.facts) > 100
    first = result.facts[0]
    assert isinstance(first.source_location, SourceLocationSheet)
    assert first.source_location.sheet == csv_adapter.SHEET_NAME
    # Row 1 holds the headings, so the first data row is row 2 -- what a reviewer will see.
    assert first.source_location.cell == "A2"
    assert first.source_label == "source_file"


def test_the_workbook_adapter_points_at_the_cell_the_value_is_in(documents, ground_truth):
    data, media_type = documents["Pacific Savings"]
    result = sheet.extract_document(data, media_type, document_id="d-sheet")
    assert result.status == "done"
    assert result.engine in {"openpyxl", "stdlib-zipfile"}

    entry = _entry(ground_truth, "Pacific Savings")
    located = {
        (fact.source_location.cell, fact.source_label): fact.raw_value
        for fact in result.facts
    }
    checked = 0
    for row in entry["rows"]:
        for field, ref in row["cells"].items():
            label = next(k for k, v in entry["header_map"].items() if v == field)
            assert (ref, label) in located, f"nothing extracted at {ref} for {label!r}"
            assert located[(ref, label)] == row["as_written"][label]
            checked += 1
    assert checked == len(entry["rows"]) * 6


def test_the_html_adapter_offsets_select_the_value_they_claim(documents):
    data, media_type = documents["Heritage Financial"]
    source = data.decode("utf-8")
    result = html_adapter.extract_document(data, media_type, document_id="d-html")
    assert result.status == "done"
    assert result.skipped == 0
    assert result.facts
    for fact in result.facts:
        location = fact.source_location
        assert isinstance(location, SourceLocationText)
        assert source[location.start : location.end] == fact.raw_value, (
            "a character offset that does not select its own value is not provenance"
        )


def test_the_html_adapter_keeps_prose_that_sits_outside_the_table(documents):
    data, media_type = documents["Heritage Financial"]
    result = html_adapter.extract_document(data, media_type, document_id="d-html")
    unlabelled = [fact for fact in result.facts if fact.source_label == ""]
    assert unlabelled, "page text outside the table was dropped"
    assert any("subject to change" in fact.raw_value for fact in unlabelled)


@pytest.mark.parametrize("institution", ["First National Bank", "Valley Community Bank"])
def test_the_text_pdf_adapter_emits_normalized_boxes_on_real_pages(documents, institution):
    data, media_type = documents[institution]
    result = pdf_text.extract_document(data, media_type, document_id="d-pdf")
    assert result.status == "done"
    assert result.engine in {"pdfplumber", "pymupdf"}
    assert result.page_count == 2
    assert result.skipped == 0
    assert result.facts
    for fact in result.facts:
        location = fact.source_location
        assert isinstance(location, SourceLocationPdf)
        assert location.page in (1, 2)
        x, y, w, h = location.bbox
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
        assert 0.0 < w <= 1.0 and 0.0 < h <= 1.0, "a zero-size box highlights nothing"
    # Not every box collapsed to the page origin, which a broken division would do.
    assert len({fact.source_location.bbox for fact in result.facts}) > 10


def test_the_text_pdf_adapter_reads_the_headings_the_document_prints(
    documents, ground_truth
):
    data, media_type = documents["First National Bank"]
    result = pdf_text.extract_document(data, media_type, document_id="d-pdf")
    entry = _entry(ground_truth, "First National Bank")
    found = {fact.source_label for fact in result.facts}
    for heading in entry["header_map"]:
        assert heading in found, f"the column heading {heading!r} was not recovered"


def test_the_contradicting_footnote_is_extracted_not_discarded(documents, ground_truth):
    """If the footnote never leaves the adapter, the review lane has nothing to catch."""
    data, media_type = documents["Valley Community Bank"]
    result = pdf_text.extract_document(data, media_type, document_id="d-valley")
    entry = _entry(ground_truth, "Valley Community Bank")
    clash = next(row for row in entry["rows"] if row["ambiguous"])["footnote_contradiction"]
    footnote_value = str(clash["footnote_interest_rate_annual_pct"])
    unlabelled = [fact for fact in result.facts if fact.source_label == ""]
    assert any(footnote_value in fact.raw_value for fact in unlabelled), (
        "the footnote figure is on the page but no fact carries it"
    )
    table_value = str(clash["table_interest_rate_annual_pct"])
    assert any(
        fact.raw_value == table_value and fact.source_label != "" for fact in result.facts
    ), "the table figure the footnote contradicts was not extracted either"


def test_a_page_of_pixels_yields_no_text_facts(documents):
    """Why `pdf_scan` has to exist: the text adapter succeeds here and finds nothing."""
    data, media_type = documents["Metro Credit Union"]
    result = pdf_text.extract_document(data, media_type, document_id="d-scan")
    assert result.status == "done"
    assert result.page_count == 2
    assert result.facts == []


# --- the two-backend modules agree -------------------------------------------


@pytest.mark.skipif(
    not (pdf_text.HAVE_PDFPLUMBER and pdf_text.HAVE_PYMUPDF),
    reason="needs both PDF backends installed to compare them",
)
def test_both_pdf_backends_read_the_same_values_off_the_same_page(documents):
    data, media_type = documents["First National Bank"]
    pages_plumber = pdf_text._pages_with_pdfplumber(data)
    pages_mupdf = pdf_text._pages_with_pymupdf(data)
    assert [(n, w, h) for n, w, h, _ in pages_plumber] == [
        (n, w, h) for n, w, h, _ in pages_mupdf
    ]
    for (_, _, _, left), (_, _, _, right) in zip(pages_plumber, pages_mupdf):
        assert [word[4] for word in left] == [word[4] for word in right]


@pytest.mark.skipif(not sheet.HAVE_OPENPYXL, reason="needs openpyxl to compare backends")
def test_both_workbook_backends_read_the_same_cells(documents):
    data, _ = documents["Pacific Savings"]
    assert sheet._read_with_openpyxl(data) == sheet._read_with_stdlib(data), (
        "the stdlib fallback and openpyxl disagree, so one of them is not reading the "
        "workbook we wrote"
    )


# --- the scan seam ------------------------------------------------------------


def test_a_scan_with_no_vision_backend_is_unavailable_rather_than_empty(documents):
    data, media_type = documents["Metro Credit Union"]
    result = pdf_scan.extract_document(data, media_type, document_id="d-scan")
    assert result.status == "unavailable"
    assert result.facts == []
    assert isinstance(result.unavailable, Unavailable)
    assert result.unavailable.reason == "no-key"
    assert result.page_count == 2


def test_the_injected_reader_is_handed_a_rasterized_page(documents):
    data, media_type = documents["Metro Credit Union"]
    seen: list[pdf_scan.ScanPage] = []

    def reader(page: pdf_scan.ScanPage) -> list[pdf_scan.VisionCell]:
        seen.append(page)
        return [
            pdf_scan.VisionCell(
                source_label="column one",
                raw_value=f"value on page {page.page}",
                bbox=(0.1, 0.2, 0.3, 0.04),
                confidence=0.77,
            )
        ]

    facts = pdf_scan.extract(data, media_type, document_id="d-scan", vision=reader, dpi=80)
    assert len(seen) == 2
    assert all(page.image_png.startswith(b"\x89PNG") for page in seen)
    assert all(page.width_px > 100 and page.height_px > 100 for page in seen)
    assert all(page.dpi == 80 for page in seen)
    assert [fact.source_location.page for fact in facts] == [1, 2]
    assert facts[0].extractor_confidence == 0.77
    assert facts[0].source_location.bbox == (0.1, 0.2, 0.3, 0.04)


def test_a_reader_returning_pixels_instead_of_fractions_has_its_facts_dropped(documents):
    data, media_type = documents["Metro Credit Union"]

    def confused(page: pdf_scan.ScanPage) -> list[pdf_scan.VisionCell]:
        return [pdf_scan.VisionCell(raw_value="7", bbox=(120.0, 300.0, 50.0, 12.0))]

    result = pdf_scan.extract_document(
        data, media_type, document_id="d-scan", vision=confused
    )
    assert result.status == "done"
    assert result.facts == []
    assert result.skipped == 2, "a box in pixels must be dropped and counted, not rescaled"


def test_a_reader_that_cannot_answer_sends_the_whole_document_to_review(documents):
    data, media_type = documents["Metro Credit Union"]

    def rate_limited(page: pdf_scan.ScanPage) -> Unavailable:
        return Unavailable(reason="rate-limited", detail="429")

    result = pdf_scan.extract_document(
        data, media_type, document_id="d-scan", vision=rate_limited
    )
    assert result.status == "unavailable"
    assert result.unavailable.reason == "rate-limited"
    assert result.facts == []


def test_importing_the_scan_adapter_reaches_no_provider_and_no_network():
    """No client at import time, so this module loads with no key and no wifi."""
    # `socket` is deliberately not in this set: pydantic imports it to describe address
    # types, which is not a client and not a call. An HTTP client or a provider SDK being
    # imported here is the thing that would mean this module needs a key to load.
    probe = (
        "import sys, backend.adapters.pdf_scan as m;"
        "roots={n.split('.')[0] for n in sys.modules};"
        "print(sorted(roots & {'openai','anthropic','google','httpx','requests','urllib3',"
        "'aiohttp','boto3'}))"
    )
    # Goes through the shared helper so the Windows closed-stdin bug (WinError 6) cannot
    # make this test red for a reason unrelated to what it asserts. See tests/probe.py.
    from backend.tests.probe import run_probe

    completed = run_probe(probe)
    assert completed.stdout.strip() == "[]", completed.stdout


# --- error containment --------------------------------------------------------

CORRUPT: dict[str, tuple[bytes, str]] = {
    "csv": (b"\xff\xfe\x00not,utf,8\x80", "text/csv"),
    "xlsx": (b"PK\x03\x04 this is not a zip central directory", XLSX),
    "html": (b"\xff\xfe<html><table><tr><td>x", "text/html"),
    "pdf": (b"%PDF-1.4\n1 0 obj << /Broken", PDF),
}


@pytest.mark.parametrize("name", sorted(CORRUPT))
def test_a_corrupt_file_reports_its_parser_error_without_raising(name):
    data, media_type = CORRUPT[name]
    result = dispatch(data, media_type, document_id=f"bad-{name}")
    assert result.status == "error"
    assert result.facts == []
    assert result.error, "the parser's own message is what the batch report shows"


def test_a_corrupt_scan_is_an_error_not_a_document_with_nothing_on_it():
    data, media_type = CORRUPT["pdf"]
    result = pdf_scan.extract_document(data, media_type, document_id="bad-scan")
    assert result.status == "error"
    assert result.facts == []


def test_one_bad_file_does_not_end_the_batch(documents):
    """The behaviour CLAUDE.md section 6 demands, exercised as a batch rather than claimed."""
    batch: list[tuple[str, bytes, str]] = [
        (f"corrupt-{name}", data, media_type) for name, (data, media_type) in CORRUPT.items()
    ]
    # Interleaved with the corrupt files, and one of every media type this package claims.
    for institution, (data, media_type) in sorted(documents.items()):
        if media_type in ADAPTERS:
            batch.append((institution, data, media_type))

    results = [
        dispatch(data, media_type, document_id=name) for name, data, media_type in batch
    ]
    statuses = {name: result.status for (name, _, _), result in zip(batch, results)}
    corrupt = {name: status for name, status in statuses.items() if name.startswith("corrupt-")}
    assert set(corrupt.values()) == {"error"}, corrupt
    good = [
        result
        for (name, _, _), result in zip(batch, results)
        if not name.startswith("corrupt-")
    ]
    # Derived, not hardcoded: the counts follow from the fixtures, so adding a seventh
    # generated document does not fail a test about error containment.
    assert len(good) == sum(
        1 for _, media_type in documents.values() if media_type in ADAPTERS
    ), statuses
    assert {result.status for result in good} == {"done"}, statuses
    # Exactly one readable document yields nothing: the scanned PDF. Dispatch sends every
    # PDF to the text adapter, which succeeds and finds no words -- which is precisely the
    # signal the pipeline uses to try `pdf_scan` instead.
    empty = [result for result in good if not result.facts]
    assert len(empty) == 1, statuses
    assert empty[0].page_count == 2


def test_the_narrative_document_has_no_adapter_in_this_package(documents):
    """Stated rather than implied: prose is the extractor agent's job, not a parser's.

    The generator emits a narrative disclosure because the problem statement asks for one,
    and nothing in `adapters/` claims to read it. A caller gets `unsupported` -- which is
    not an error -- instead of a parser quietly returning nothing from a file it cannot
    handle.
    """
    data, media_type = documents["Summit Trust"]
    assert media_type == "text/plain"
    assert media_type not in ADAPTERS
    result = dispatch(data, media_type, document_id="d-narrative")
    assert result.status == "unsupported"


def test_an_unregistered_media_type_is_unsupported_not_an_error():
    result = dispatch(b"\x00\x01", "application/x-nobody-asked", document_id="odd")
    assert result.status == "unsupported"
    assert result.facts == []
    assert "no adapter registered" in (result.error or "")


def test_every_registered_adapter_answers_for_its_own_media_types():
    assert ADAPTERS, "the dispatch table is empty"
    for media_type, adapter in ADAPTERS.items():
        result = adapter(b"", media_type, document_id="empty")
        assert result.status in {"done", "error", "unsupported"}
        assert result.media_type == media_type


def test_an_adapter_refuses_a_media_type_it_does_not_own():
    assert csv_adapter.extract_document(b"a,b\n1,2", "text/html").status == "unsupported"
    assert pdf_text.extract_document(b"%PDF", XLSX).status == "unsupported"
    assert sheet.extract_document(b"PK", PDF).status == "unsupported"


# --- Law II -------------------------------------------------------------------

#: Words that may not appear under `adapters/`. Spelled in pieces nowhere near a pack, and
#: checked case-insensitively.
FORBIDDEN_TERMS = (
    "apy",
    "money market",
    "rate_sheet",
    "interest",
    "deposit",
    "first national",
    "metro credit",
    "heritage financial",
    "pacific savings",
    "summit trust",
    "valley community",
)


def _offending_terms(text: str) -> set[str]:
    lowered = text.lower()
    return {term for term in FORBIDDEN_TERMS if term in lowered}


def test_no_domain_noun_reaches_the_adapters():
    sources = sorted(ADAPTER_PACKAGE.glob("*.py"))
    assert len(sources) >= 6, f"the scanner found almost no adapters: {sources}"
    for path in sources:
        found = _offending_terms(path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} names a domain noun: {sorted(found)}"


def test_the_domain_noun_scanner_is_not_broken():
    """Law II's positive control: a scanner broken by a typo also finds nothing.

    The fixture generator is the opposite case -- it must name institutions, so it is the
    file that proves the scanner above can still see what it is looking for.
    """
    text = Path(make_documents.__file__).read_text(encoding="utf-8")
    found = _offending_terms(text)
    assert len(found) >= 5, f"the scanner cannot even see the generator's nouns: {found}"
