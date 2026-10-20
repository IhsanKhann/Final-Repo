"""Builds the six source documents the pipeline ingests, out of ps06's extracted rows.

Why it exists: `ps06_sample_rate_sheets.csv` is already-extracted tabular data, so on its
own it cannot demonstrate multi-format ingestion -- there is nothing to ingest. This module
reconstructs the problem the statement describes by re-expressing the same rows as six
documents, one institution per format, each using different words, units and layout for the
same quantities. One of them quotes a monthly figure (so the x12 conversion is what recovers
the truth) and one contradicts itself in a footnote (so the review lane has something real
to catch).

What it refuses to do: it refuses to vary. No clock, no RNG, no dict-ordering dependence, no
PDF creation-date metadata; the one piece of per-run entropy PyMuPDF emits (the trailer
`/ID`) is overwritten in place with a fixed, same-length value. Same CSV in, byte-identical
documents out, because a demo that drifts cannot be rehearsed. (The PDF `/Producer` string
still carries the PyMuPDF version, so byte-equality holds per library version -- which is
what `requirements.txt` pins.)

It also refuses to invent an answer: every value written into a document comes from a CSV
row, and `ground_truth.json` records, per document and per row, both the canonical value and
the exact string as written -- so block 9 scores against something known by construction
rather than against our own extractor.

It refuses to own the vocabulary, too. The column headings and the narrative phrases are
imported from `make_golden_set.REPORTING_STYLE`, never copied: that table is what the golden
set's `source_label` column was built from, and a label spelled one way here and another way
there is ground truth describing documents nobody generated -- drift with nothing to catch
it. One heading is ours, `"Product"`, because `product_type` is not one of the five fields
that table declares.

This is a fixture generator, not the engine. Institution names and their vocabulary
necessarily appear here; that is why Law II scopes to `engine/`, `adapters/`, `api/` and the
frontend, and `tests/test_adapters.py` keeps a positive control pointed at this file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

# The single source of truth for terminology. Imported, not copied, on purpose -- see the
# module docstring. This module never writes to it.
from backend.eval.make_golden_set import PROPOSED_FIELD, REPORTING_STYLE

# --- Where things live --------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO_ROOT / "data" / "samples" / "ps06_sample_rate_sheets.csv"
DEFAULT_OUT = Path(__file__).resolve().parent / "generated"

#: Bumped by hand when a layout changes, so a stale fixture is detectable rather than
#: merely different.
GENERATOR_VERSION = "1"

# --- Deterministic PDF emission ----------------------------------------------

_PAGE_W = 595.0
_PAGE_H = 842.0
_FONT = "helv"
_ROWS_PER_PAGE = 14
#: Grayscale at 120 dpi: large enough to read, small enough that the fixture stays in git,
#: and no text layer survives rasterization -- which is the whole point of that document.
_SCAN_DPI = 120

#: PyMuPDF writes a random document /ID into the trailer on every save. Replacing each hex
#: group with zeros of the same length keeps every xref offset valid while removing the only
#: per-run entropy in the file.
_TRAILER_ID = re.compile(rb"(/ID\s*\[\s*<)([0-9A-Fa-f]*)(>\s*<)([0-9A-Fa-f]*)(>\s*\])")


def _fixed_id(match: re.Match[bytes]) -> bytes:
    return (
        match.group(1)
        + b"0" * len(match.group(2))
        + match.group(3)
        + b"0" * len(match.group(4))
        + match.group(5)
    )


#: The trailer sits at the end of the file. Scoping the substitution to the tail keeps the
#: pattern away from compressed image streams, where a chance match would corrupt the PDF.
_TRAILER_WINDOW = 4096


def _pdf_bytes(doc: fitz.Document, *, deflate_images: bool = False) -> bytes:
    doc.set_metadata({})  # drops CreationDate / ModDate
    raw = doc.tobytes(garbage=0, deflate=False, deflate_images=deflate_images)
    split = max(0, len(raw) - _TRAILER_WINDOW)
    head, tail = raw[:split], raw[split:]
    patched, count = _TRAILER_ID.subn(_fixed_id, tail, count=1)
    if count != 1:
        # Loud rather than silent: an unpatched /ID is per-run entropy, and the whole
        # point of this module is that the demo cannot drift.
        raise RuntimeError("no trailer /ID found to normalize; output would not be stable")
    return head + patched


# --- Source rows --------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One ps06 record, with the strings exactly as the CSV spells them.

    Both forms are kept on purpose: the float is the truth a scorer compares against, the
    string is what gets written into a document, and rounding one into the other is how
    fixtures quietly stop matching their own ground truth.
    """

    csv_index: int
    source_file: str
    institution: str
    product: str
    term_months: int
    rate_pct: float
    rate_text: str
    apy_pct: float
    apy_text: str
    min_deposit: int
    effective_date: str
    extraction_confidence: float
    needs_review: bool


def load_rows(csv_path: Path = DEFAULT_CSV) -> list[Row]:
    """Read ps06 in file order. Order is part of the fixture, so it is never sorted."""
    with open(csv_path, newline="", encoding="utf-8") as handle:
        return [
            Row(
                csv_index=i,
                source_file=r["source_file"],
                institution=r["institution_name"],
                product=r["product_type"],
                term_months=int(r["term_months"]),
                rate_pct=float(r["rate_pct"]),
                rate_text=r["rate_pct"],
                apy_pct=float(r["apy_pct"]),
                apy_text=r["apy_pct"],
                min_deposit=int(r["min_deposit"]),
                effective_date=r["effective_date"],
                extraction_confidence=float(r["extraction_confidence"]),
                needs_review=r["needs_review"].strip().lower() == "true",
            )
            for i, r in enumerate(csv.DictReader(handle))
        ]


# --- Formatting helpers (every one is pure and total) -------------------------

_MONTH_ABBR = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun",
    "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}
_MONTH_FULL = {
    "01": "January", "02": "February", "03": "March", "04": "April", "05": "May",
    "06": "June", "07": "July", "08": "August", "09": "September", "10": "October",
    "11": "November", "12": "December",
}


def _iso(date: str) -> str:
    return date


def _us(date: str) -> str:
    y, m, d = date.split("-")
    return f"{m}/{d}/{y}"


def _abbr(date: str) -> str:
    y, m, d = date.split("-")
    return f"{d} {_MONTH_ABBR[m]} {y}"


def _long(date: str) -> str:
    y, m, d = date.split("-")
    return f"{_MONTH_FULL[m]} {int(d)}, {y}"


def _money(amount: int) -> str:
    return f"${amount:,}"


def _col_letter(index_zero_based: int) -> str:
    """0 -> A. Duplicated rather than imported from adapters: a change there must not be
    able to move a fixture's bytes."""
    letters = ""
    n = index_zero_based + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _monthly_text(rate_pct: float) -> str:
    """The nominal quoted per month.

    Four decimals, not more, because `make_golden_set` writes `value_as_printed` as
    `f"{rate/12:.4f}"` and the document has to print the figure the golden set says it
    prints. The cost is that x12 recovers the annual rate to within 0.0005 rather than
    exactly, so a scorer must compare numerically with a tolerance -- which is recorded
    per row as `recovered_annual_pct`, not left for anyone to rediscover.
    """
    return f"{rate_pct / 12.0:.4f}"


def _recovered_annual(monthly_text: str) -> float:
    return round(float(monthly_text) * 12.0, 6)


# --- PDF table painting -------------------------------------------------------

_COL_X = (45.0, 150.0, 232.0, 302.0, 372.0, 458.0)
_HEADER_Y = 118.0
_ROW_DY = 22.0


def _paint_table_page(
    doc: fitz.Document,
    *,
    title: str,
    subtitle: str,
    headers: tuple[str, ...],
    body: list[tuple[str, ...]],
    footnote: str | None,
) -> None:
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text((45.0, 62.0), title, fontname=_FONT, fontsize=15)
    page.insert_text((45.0, 84.0), subtitle, fontname=_FONT, fontsize=9)
    for x, text in zip(_COL_X, headers):
        page.insert_text((x, _HEADER_Y), text, fontname=_FONT, fontsize=9)
    page.draw_line(fitz.Point(45.0, _HEADER_Y + 6.0), fitz.Point(545.0, _HEADER_Y + 6.0))
    y = _HEADER_Y + _ROW_DY
    for cells in body:
        for x, text in zip(_COL_X, cells):
            page.insert_text((x, y), text, fontname=_FONT, fontsize=9)
        y += _ROW_DY
    if footnote is not None:
        page.insert_text((45.0, y + 18.0), footnote, fontname=_FONT, fontsize=8)


def _paginate(rows: list[Row]) -> list[list[Row]]:
    return [rows[i : i + _ROWS_PER_PAGE] for i in range(0, len(rows), _ROWS_PER_PAGE)]


# --- Minimal deterministic XLSX writer ---------------------------------------
#
# openpyxl is not installable here and pandas cannot write xlsx without it. An xlsx is a
# zip of XML and both are stdlib, so this writes a real one rather than dropping the one
# institution whose monthly quote is the only proof the unit converter does anything.
# Entries are STORED, not deflated, and stamped with a fixed 1980 timestamp: the output must
# not depend on the host's zlib version or on the clock.

_XLSX_FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _xlsx_bytes(sheet_name: str, grid: list[list[object]]) -> bytes:
    """`grid` holds str (shared string) or int/float (numeric) cells, row-major from A1."""
    shared: list[str] = []
    index_of: dict[str, int] = {}
    rows_xml: list[str] = []
    for r, row in enumerate(grid, start=1):
        cells_xml: list[str] = []
        for c, value in enumerate(row):
            ref = f"{_col_letter(c)}{r}"
            if isinstance(value, str):
                if value not in index_of:
                    index_of[value] = len(shared)
                    shared.append(value)
                cells_xml.append(f'<c r="{ref}" t="s"><v>{index_of[value]}</v></c>')
            else:
                cells_xml.append(f'<c r="{ref}"><v>{value}</v></c>')
        rows_xml.append(f'<row r="{r}">{"".join(cells_xml)}</row>')

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    members = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel_ns}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{ns}" xmlns:r="{rel_ns}">'
            f'<sheets><sheet name="{_xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel_ns}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{rel_ns}/sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{ns}"><sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
        ),
        "xl/sharedStrings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<sst xmlns="{ns}" count="{len(shared)}" uniqueCount="{len(shared)}">'
            + "".join(f"<si><t>{_xml_escape(s)}</t></si>" for s in shared)
            + "</sst>"
        ),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in (
            "[Content_Types].xml",
            "_rels/.rels",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
            "xl/worksheets/sheet1.xml",
            "xl/sharedStrings.xml",
        ):
            info = zipfile.ZipInfo(name, date_time=_XLSX_FIXED_DATE)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, members[name].encode("utf-8"))
    return buffer.getvalue()


# --- The six documents --------------------------------------------------------
#
# Each builder returns (filename, media_type, bytes, per-row ground truth, header map).
# The header map is the terminology claim: it says, per document, which written column
# heading means which canonical field, so mapping accuracy in block 9 has an answer key.

_SHEET_NAME = "Rates"

#: Ours, not the imported table's: `product_type` is not one of the five fields the golden
#: set declares a label for, and a table needs a first column.
_PRODUCT_HEADING = "Product"

#: Column order is this module's business; the words in the headings are not. Every tabular
#: format lays the columns out the same way so that a difference between two documents is
#: always a difference in vocabulary, never in which column is which.
_COLUMN_ORDER = ("term_months", "rate_pct", "apy_pct", "min_deposit", "effective_date")


def _labels(institution: str) -> dict[str, str]:
    style = REPORTING_STYLE.get(institution)
    if style is None:
        raise ValueError(
            f"{institution!r} has no entry in make_golden_set.REPORTING_STYLE, so there is "
            "no agreed vocabulary to render it with"
        )
    return style["labels"]


def _declared_format(institution: str) -> str:
    return REPORTING_STYLE[institution]["format"]


def _headers(institution: str) -> tuple[str, ...]:
    labels = _labels(institution)
    return (_PRODUCT_HEADING,) + tuple(labels[column] for column in _COLUMN_ORDER)


def _header_map(institution: str) -> dict[str, str]:
    """Written heading -> canonical field. This is the answer key for mapping accuracy."""
    labels = _labels(institution)
    mapping = {_PRODUCT_HEADING: "product_type"}
    for column in _COLUMN_ORDER:
        mapping[labels[column]] = PROPOSED_FIELD[column]
    return mapping


def _truth(row: Row, *, page: int | None, as_written: dict[str, str], **extra: object) -> dict:
    record = {
        "csv_index": row.csv_index,
        "product_type": row.product,
        "term_months": row.term_months,
        "interest_rate_annual_pct": row.rate_pct,
        "annual_percentage_yield_pct": row.apy_pct,
        "minimum_deposit_usd": row.min_deposit,
        "effective_date": row.effective_date,
        "upstream_extraction_confidence": row.extraction_confidence,
        "upstream_needs_review": row.needs_review,
        "page": page,
        "as_written": as_written,
        "ambiguous": False,
        "note": None,
    }
    record.update(extra)
    return record


_FIRST_NATIONAL = "First National Bank"


def _build_first_national(rows: list[Row]) -> dict:
    """Conventional headings, ISO dates, bare percentages: the control case."""
    headers = _headers(_FIRST_NATIONAL)
    doc = fitz.open()
    truths: list[dict] = []
    for page_no, page_rows in enumerate(_paginate(rows), start=1):
        body = []
        for row in page_rows:
            cells = (
                row.product, str(row.term_months), row.rate_text, row.apy_text,
                _money(row.min_deposit), _iso(row.effective_date),
            )
            body.append(cells)
            truths.append(
                _truth(row, page=page_no, as_written=dict(zip(headers, cells)))
            )
        _paint_table_page(
            doc,
            title=_FIRST_NATIONAL,
            subtitle=f"Deposit Account Rates - page {page_no}",
            headers=headers,
            body=body,
            footnote=None,
        )
    payload = _pdf_bytes(doc)
    doc.close()
    return {
        "file": "first_national_bank_rates.pdf",
        "media_type": "application/pdf",
        "format": _declared_format(_FIRST_NATIONAL),
        "bytes": payload,
        "rows": truths,
        "header_map": _header_map(_FIRST_NATIONAL),
    }


_METRO = "Metro Credit Union"


def _build_metro(rows: list[Row]) -> dict:
    """Same table, different words, then flattened to pixels so there is no text layer."""
    headers = _headers(_METRO)
    source = fitz.open()
    truths: list[dict] = []
    for page_no, page_rows in enumerate(_paginate(rows), start=1):
        body = []
        for row in page_rows:
            cells = (
                row.product, str(row.term_months), f"{row.rate_text}%", f"{row.apy_text}%",
                _money(row.min_deposit), _us(row.effective_date),
            )
            body.append(cells)
            truths.append(
                _truth(row, page=page_no, as_written=dict(zip(headers, cells)))
            )
        _paint_table_page(
            source,
            title=_METRO,
            subtitle=f"Share Account Disclosure - page {page_no}",
            headers=headers,
            body=body,
            footnote=None,
        )

    scan = fitz.open()
    for page in source:
        pixmap = page.get_pixmap(dpi=_SCAN_DPI, colorspace=fitz.csGRAY)
        target = scan.new_page(width=_PAGE_W, height=_PAGE_H)
        target.insert_image(fitz.Rect(0, 0, _PAGE_W, _PAGE_H), stream=pixmap.tobytes("png"))
    payload = _pdf_bytes(scan, deflate_images=True)
    source.close()
    scan.close()
    return {
        "file": "metro_credit_union_rates_scan.pdf",
        "media_type": "application/pdf",
        "format": _declared_format(_METRO),
        "bytes": payload,
        "rows": truths,
        "header_map": _header_map(_METRO),
    }


_HERITAGE = "Heritage Financial"


def _build_heritage(rows: list[Row]) -> dict:
    """Lowercase headings and a space before the percent sign, per DATASETS.md section 1."""
    headers = _headers(_HERITAGE)
    truths: list[dict] = []
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        '<head><meta charset="utf-8"><title>Heritage Financial - Deposit Rates</title></head>',
        "<body>",
        f"<h1>{_HERITAGE}</h1>",
        "<p>Current deposit rates, quoted per annum.</p>",
        "<table>",
        "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>",
    ]
    for row in rows:
        cells = (
            row.product, str(row.term_months), f"{row.rate_text} %", f"{row.apy_text} %",
            _money(row.min_deposit), _abbr(row.effective_date),
        )
        lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        truths.append(_truth(row, page=None, as_written=dict(zip(headers, cells))))
    lines += [
        "</table>",
        "<p>Rates are subject to change without notice.</p>",
        "</body>",
        "</html>",
        "",
    ]
    return {
        "file": "heritage_financial_rates.html",
        "media_type": "text/html",
        "format": _declared_format(_HERITAGE),
        "bytes": "\n".join(lines).encode("utf-8"),
        "rows": truths,
        "header_map": _header_map(_HERITAGE),
    }


_PACIFIC = "Pacific Savings"


def _build_pacific(rows: list[Row]) -> dict:
    """The one document that quotes a monthly nominal. x12 is what recovers the truth."""
    headers = _headers(_PACIFIC)
    grid: list[list[object]] = [list(headers)]
    truths: list[dict] = []
    for offset, row in enumerate(rows):
        monthly = _monthly_text(row.rate_pct)
        grid.append([
            row.product, row.term_months, float(monthly), row.apy_pct,
            row.min_deposit, row.effective_date,
        ])
        sheet_row = offset + 2  # row 1 holds the headings
        written = (
            row.product, str(row.term_months), monthly, row.apy_text,
            str(row.min_deposit), row.effective_date,
        )
        truths.append(
            _truth(
                row,
                page=None,
                as_written=dict(zip(headers, written)),
                cells={
                    "product_type": f"A{sheet_row}",
                    "term_months": f"B{sheet_row}",
                    "interest_rate_annual_pct": f"C{sheet_row}",
                    "annual_percentage_yield_pct": f"D{sheet_row}",
                    "minimum_deposit_usd": f"E{sheet_row}",
                    "effective_date": f"F{sheet_row}",
                },
                nominal_monthly_pct=float(monthly),
                recovered_annual_pct=_recovered_annual(monthly),
                note="Nominal is quoted per month; x12 recovers interest_rate_annual_pct.",
            )
        )
    return {
        "file": "pacific_savings_rates.xlsx",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "format": _declared_format(_PACIFIC),
        "bytes": _xlsx_bytes(_SHEET_NAME, grid),
        "rows": truths,
        "sheet": _SHEET_NAME,
        "header_map": _header_map(_PACIFIC),
    }


_SUMMIT = "Summit Trust"


def _build_summit(rows: list[Row]) -> dict:
    """No table at all: the same quantities buried in sentences, which is the extractor
    agent's case rather than a parser's.

    The phrases are the golden set's `labels` verbatim, so each sentence is built around
    them and each value sits immediately after the phrase that claims it. A demand product
    still reads "for a term of 0 months" -- clumsy prose, but 0 is a real value (no term),
    and replacing it with "none" would make the figure unrecoverable.
    """
    labels = _labels(_SUMMIT)
    # "pays ... annually" is a label with a hole in it, not a substring, so the sentence is
    # built from its two halves rather than from a hand-copied phrase.
    rate_before, rate_after = (part.strip() for part in labels["rate_pct"].split("..."))
    truths: list[dict] = []
    paragraphs = [
        _SUMMIT,
        "Deposit Disclosure Statement",
        "",
        "The rates described below are offered to personal depositors at all branches.",
        "",
    ]
    for row in rows:
        term_text = f"{row.term_months} months"
        if row.term_months == 0:
            term_text += " (payable on demand)"
        money = _money(row.min_deposit)
        date_text = _long(row.effective_date)
        sentence = (
            f"The {row.product} account, {labels['term_months']} {term_text}, "
            f"{rate_before} {row.rate_text}% {rate_after} on {labels['min_deposit']} {money}, "
            f"with an {labels['apy_pct']} {row.apy_text}%, "
            f"{labels['effective_date']} {date_text}."
        )
        paragraphs.append(sentence)
        paragraphs.append("")
        truths.append(
            _truth(
                row,
                page=None,
                as_written={
                    _PRODUCT_HEADING: row.product,
                    labels["term_months"]: term_text,
                    labels["rate_pct"]: f"{row.rate_text}%",
                    labels["apy_pct"]: f"{row.apy_text}%",
                    labels["min_deposit"]: money,
                    labels["effective_date"]: date_text,
                },
                note="Narrative prose: no table, no headings. One sentence per record.",
            )
        )
    paragraphs.append(f"Rates are subject to change at the discretion of {_SUMMIT}.")
    paragraphs.append("")
    return {
        "file": "summit_trust_disclosure.txt",
        "media_type": "text/plain",
        "format": _declared_format(_SUMMIT),
        "bytes": "\n".join(paragraphs).encode("utf-8"),
        "rows": truths,
        "header_map": _header_map(_SUMMIT),
    }


#: The footnote restates the first row of each page with a different figure. This is the
#: ambiguity case: both numbers are on the page, the table is the one ps06 vouches for, and
#: a pipeline that silently prefers either one without flagging it is wrong.
_FOOTNOTE_DELTA_PCT = 0.15


_VALLEY = "Valley Community Bank"


def _build_valley(rows: list[Row]) -> dict:
    """Its two rate headings carry the footnote marker the golden set declares (`Rate*`),
    and the footnote under each page disagrees with the row it points at."""
    headers = _headers(_VALLEY)
    doc = fitz.open()
    truths: list[dict] = []
    for page_no, page_rows in enumerate(_paginate(rows), start=1):
        body = []
        for position, row in enumerate(page_rows):
            cells = (
                row.product, str(row.term_months), row.rate_text, row.apy_text,
                _money(row.min_deposit), _iso(row.effective_date),
            )
            body.append(cells)
            contradicted = position == 0
            extra: dict[str, object] = {}
            if contradicted:
                footnote_value = round(row.rate_pct + _FOOTNOTE_DELTA_PCT, 3)
                extra = {
                    "ambiguous": True,
                    "footnote_contradiction": {
                        "table_interest_rate_annual_pct": row.rate_pct,
                        "footnote_interest_rate_annual_pct": footnote_value,
                        "page": page_no,
                    },
                    "note": (
                        "The page footnote restates this row with a different rate. The "
                        "table value is the one ps06 vouches for; the field must reach the "
                        "review lane, not be auto-accepted from either number."
                    ),
                }
            truths.append(
                _truth(row, page=page_no, as_written=dict(zip(headers, cells)), **extra)
            )
        first = page_rows[0]
        footnote = (
            f"* The {first.product} rate shown above is indicative. Effective "
            f"{_iso(first.effective_date)} the posted rate for this product is "
            f"{round(first.rate_pct + _FOOTNOTE_DELTA_PCT, 3)}% p.a."
        )
        _paint_table_page(
            doc,
            title=_VALLEY,
            subtitle=f"Schedule of Deposit Rates - page {page_no}",
            headers=headers,
            body=body,
            footnote=footnote,
        )
    payload = _pdf_bytes(doc)
    doc.close()
    return {
        "file": "valley_community_bank_rates.pdf",
        "media_type": "application/pdf",
        "format": _declared_format(_VALLEY),
        "bytes": payload,
        "rows": truths,
        "header_map": _header_map(_VALLEY),
    }


#: Institution -> builder. A tuple, not a dict comprehension, because the output order of
#: ground_truth.json is part of the fixture.
BUILDERS = (
    (_FIRST_NATIONAL, _build_first_national),
    (_METRO, _build_metro),
    (_HERITAGE, _build_heritage),
    (_PACIFIC, _build_pacific),
    (_SUMMIT, _build_summit),
    (_VALLEY, _build_valley),
)


def _document_id(institution: str) -> str:
    return "doc-" + institution.lower().replace(" ", "-")


# --- Entry point --------------------------------------------------------------


def generate(csv_path: Path = DEFAULT_CSV, out_dir: Path = DEFAULT_OUT) -> dict:
    """Write the six documents plus `ground_truth.json`; return the ground truth."""
    rows = load_rows(csv_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    documents = []
    for institution, build in BUILDERS:
        mine = [r for r in rows if r.institution == institution]
        if not mine:
            raise ValueError(f"no rows for {institution!r}: the fixture spec is out of date")
        built = build(mine)
        payload = built["bytes"]
        (out_dir / built["file"]).write_bytes(payload)
        entry = {
            "document_id": _document_id(institution),
            "institution": institution,
            "file": built["file"],
            "media_type": built["media_type"],
            "format": built["format"],
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "row_count": len(built["rows"]),
            "header_map": built["header_map"],
            "rows": built["rows"],
        }
        if "sheet" in built:
            entry["sheet"] = built["sheet"]
        documents.append(entry)

    ground_truth = {
        "generator_version": GENERATOR_VERSION,
        "source_csv": csv_path.name,
        "source_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "source_row_count": len(rows),
        "documents": documents,
    }
    text = json.dumps(ground_truth, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    with open(out_dir / "ground_truth.json", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return ground_truth


def main() -> None:
    truth = generate()
    for document in truth["documents"]:
        print(f"{document['file']:40s} {document['size_bytes']:>9d}  {document['sha256'][:16]}")


if __name__ == "__main__":
    main()
