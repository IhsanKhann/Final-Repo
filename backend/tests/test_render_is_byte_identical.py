"""Law IV: the export is a render, not a generation. Same data in, byte-identical out.

An export that differs between two runs on identical data cannot be used as evidence, and
evidence is the product. This test exists to catch the four things that quietly break it:
a timestamp written into the file, dict iteration order leaking into column order, a float
reformatted on the way out, and a platform line ending.
"""

from __future__ import annotations

from backend.engine.contracts import Conversion, Mapping, SourceLocationPdf, SourceLocationSheet
from backend.engine.render import render_csv, render_json

FIELD_ORDER = ("f_alpha", "f_beta", "f_gamma")


def _mappings() -> list[Mapping]:
    return [
        Mapping(
            id="m2",
            document_id="doc-b",
            source_label="label two",
            target_field="f_beta",
            raw_value="0.3383",
            raw_unit="u_month",
            value="4.0596",
            unit="u_year",
            confidence=0.93,
            status="auto",
            reason="precedent",
            conversion=Conversion(factor=12.0, rule_id="c1", formula_text="x 12 (monthly -> annual)"),
            source_location=SourceLocationSheet(sheet="Sheet1", cell="B12"),
        ),
        Mapping(
            id="m1",
            document_id="doc-a",
            source_label="label one",
            target_field="f_alpha",
            raw_value="1.36",
            value="1.36",
            confidence=0.97,
            status="auto",
            source_location=SourceLocationPdf(page=4, bbox=(0.1, 0.2, 0.3, 0.05)),
        ),
        Mapping(
            id="m3",
            document_id="doc-a",
            source_label="label three",
            target_field="",
            raw_value="n/a",
            value="",
            confidence=0.11,
            status="missing",
            reason="below the review threshold",
        ),
    ]


def test_the_same_data_renders_the_same_csv_bytes():
    first = render_csv(_mappings(), FIELD_ORDER)
    second = render_csv(_mappings(), FIELD_ORDER)
    assert first == second


def test_the_same_data_renders_the_same_json_bytes():
    assert render_json(_mappings(), FIELD_ORDER) == render_json(_mappings(), FIELD_ORDER)


def test_input_order_does_not_change_the_output():
    """Row order must come from a sort, not from the order mappings happened to arrive."""
    forward = _mappings()
    backward = list(reversed(_mappings()))
    assert render_csv(forward, FIELD_ORDER) == render_csv(backward, FIELD_ORDER)
    assert render_json(forward, FIELD_ORDER) == render_json(backward, FIELD_ORDER)


def test_columns_follow_the_declared_order_not_the_data():
    header = render_csv(_mappings(), FIELD_ORDER).decode().splitlines()[0]
    assert header == "document_id,record,f_alpha,f_beta,f_gamma"
    # A field the pack declares but no document filled must still have its column.
    assert ",f_gamma" in header


def test_one_row_per_record_not_per_document():
    """A document is not a record: doc-a holds two, and they must stay two rows.

    The key rides on the Mapping, so a caller cannot forget to pass it and silently get
    the document-level grouping that made the dataset short.
    """
    keyed = [
        m.model_copy(update={"record_key": key})
        for m, key in zip(_mappings(), ("row:9", "row:2", "row:3"))
    ]
    rendered = render_csv(keyed, FIELD_ORDER).decode().splitlines()
    assert len(rendered) - 1 == 3, "three records, so record-level grouping gives 3 rows"
    assert "row:2" in rendered[1]

    # Unkeyed mappings are one record per document -- correct for a single-record file.
    collapsed = render_csv(_mappings(), FIELD_ORDER).decode().splitlines()
    assert len(collapsed) - 1 == 2


def test_the_line_ending_is_lf_on_every_platform():
    """CRLF here would make the same export differ between a developer and CI."""
    rendered = render_csv(_mappings(), FIELD_ORDER)
    assert b"\r\n" not in rendered


def test_a_missing_value_is_written_not_dropped():
    """Law V reaching the export: the field appears, empty, rather than vanishing."""
    text = render_csv(_mappings(), FIELD_ORDER).decode()
    assert "doc-a" in text
    assert "f_gamma" in text.splitlines()[0]


def test_the_audit_export_carries_provenance_for_every_row():
    text = render_csv(_mappings(), FIELD_ORDER, audit=True).decode()
    header = text.splitlines()[0]
    for column in ("_status", "_source_page", "_source_bbox", "_formula_text", "_reason"):
        assert column in header, f"the audit export lost {column}"
    assert "x 12 (monthly -> annual)" in text, "the human-readable formula did not survive"


def test_the_audit_export_is_also_byte_identical():
    assert render_csv(_mappings(), FIELD_ORDER, audit=True) == render_csv(
        _mappings(), FIELD_ORDER, audit=True
    )


def test_this_guard_can_actually_fail():
    """Positive control: changing one value must change the bytes."""
    baseline = render_csv(_mappings(), FIELD_ORDER)
    altered = _mappings()
    altered[0] = altered[0].model_copy(update={"value": "9.9999"})
    assert render_csv(altered, FIELD_ORDER) != baseline
