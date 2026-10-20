"""Reads a PDF that has a text layer into facts located by page and normalized box.

Why it exists: this is the format where provenance is hardest and matters most -- the demo's
answer to "how do we know it didn't hallucinate this number" is a highlighted rectangle on a
page. Both candidate libraries report absolute points, so **the division by page width and
height happens here, once**, via `base.normalized_bbox`, and the result is validated before
`SourceLocationPdf` is constructed. Nothing downstream, and certainly nothing in the UI,
ever sees a point.

Structure is reconstructed geometrically rather than assumed: words are grouped into lines
by their vertical position, lines into cells by horizontal gaps, and the most common cell
count on a page is taken to be its table. The first such line names the columns; every other
line on the page is still emitted, with an empty `source_label`, because a footnote is
exactly the content an ambiguity has to be found in and dropping it would hide the one case
the review lane exists for.

Two backends: `pdfplumber` when it imports, else PyMuPDF. They are not a primary and a stub
-- both are real parsers, both feed the same geometry code, and the one that ran is recorded
on the result.

What it refuses to do: it refuses to interpret a heading or a value, it refuses to emit a box
it has not checked, and it refuses to raise.
"""

from __future__ import annotations

import io
from collections import Counter

from backend.adapters.base import (
    UNLABELLED,
    AdapterResult,
    ExtractedFact,
    normalized_bbox,
    run_contained,
    snippet,
    unsupported,
)
from backend.engine.contracts import SourceLocationPdf

MEDIA_TYPES = frozenset({"application/pdf"})

#: (x0, top, x1, bottom, text) in absolute page points, top-left origin. Both backends
#: normalize into this shape, which is the only thing the geometry code below knows about.
Word = tuple[float, float, float, float, str]

#: Two words belong to the same line if their tops differ by less than this. Loose enough
#: for a baseline wobble, tight enough not to merge a 22pt row pitch.
_LINE_TOLERANCE = 3.0
#: A horizontal gap wider than this starts a new cell. A word space at 9pt is about 2.5pt
#: and the generated tables leave at least 20pt between columns, so this sits between them.
_CELL_GAP = 12.0
#: Fewer columns than this is prose that happens to have gaps in it, not a table row.
_MIN_TABLE_COLUMNS = 3

try:
    import pdfplumber as _pdfplumber

    HAVE_PDFPLUMBER = True
except ImportError:  # pragma: no cover - exercised only on a host without pdfplumber
    _pdfplumber = None
    HAVE_PDFPLUMBER = False

try:
    import fitz as _fitz

    HAVE_PYMUPDF = True
except ImportError:  # pragma: no cover - exercised only on a host without PyMuPDF
    _fitz = None
    HAVE_PYMUPDF = False


#: page number (1-based), page width, page height, words
Page = tuple[int, float, float, list[Word]]


def _pages_with_pdfplumber(data: bytes) -> list[Page]:
    pages: list[Page] = []
    with _pdfplumber.open(io.BytesIO(data)) as document:
        for number, page in enumerate(document.pages, start=1):
            words = [
                (
                    float(word["x0"]), float(word["top"]),
                    float(word["x1"]), float(word["bottom"]),
                    str(word["text"]),
                )
                for word in page.extract_words(use_text_flow=False)
            ]
            pages.append((number, float(page.width), float(page.height), words))
    return pages


def _pages_with_pymupdf(data: bytes) -> list[Page]:
    pages: list[Page] = []
    document = _fitz.open(stream=data, filetype="pdf")
    try:
        for number, page in enumerate(document, start=1):
            words = [
                (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]))
                for w in page.get_text("words")
            ]
            rect = page.rect
            pages.append((number, float(rect.width), float(rect.height), words))
    finally:
        document.close()
    return pages


#: text, x0, top, x1, bottom
Cell = tuple[str, float, float, float, float]


def _lines(words: list[Word]) -> list[list[Cell]]:
    """Words -> lines of cells, by geometry alone."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w[1], w[0]))
    grouped: list[list[Word]] = [[ordered[0]]]
    for word in ordered[1:]:
        if abs(word[1] - grouped[-1][0][1]) <= _LINE_TOLERANCE:
            grouped[-1].append(word)
        else:
            grouped.append([word])

    lines: list[list[Cell]] = []
    for group in grouped:
        row = sorted(group, key=lambda w: w[0])
        cells: list[Cell] = []
        parts: list[str] = [row[0][4]]
        x0, top, x1, bottom = row[0][0], row[0][1], row[0][2], row[0][3]
        for word in row[1:]:
            if word[0] - x1 > _CELL_GAP:
                cells.append((" ".join(parts), x0, top, x1, bottom))
                parts = [word[4]]
                x0, top, x1, bottom = word[0], word[1], word[2], word[3]
            else:
                parts.append(word[4])
                x1 = max(x1, word[2])
                top = min(top, word[1])
                bottom = max(bottom, word[3])
        cells.append((" ".join(parts), x0, top, x1, bottom))
        lines.append(cells)
    return lines


def _table_width(lines: list[list[Cell]]) -> int | None:
    """The column count of this page's table, or None if there is no table on it."""
    counts = Counter(len(cells) for cells in lines if len(cells) >= _MIN_TABLE_COLUMNS)
    if not counts:
        return None
    # Sorted, not `most_common`: a tie has to break the same way on every run.
    width, occurrences = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return width if occurrences >= 2 else None  # a heading with no rows under it is prose


def _line_bbox(cells: list[Cell]) -> tuple[float, float, float, float]:
    return (
        min(cell[1] for cell in cells),
        min(cell[2] for cell in cells),
        max(cell[3] for cell in cells),
        max(cell[4] for cell in cells),
    )


def extract_document(
    data: bytes, media_type: str = "application/pdf", *, document_id: str = ""
) -> AdapterResult:
    if media_type not in MEDIA_TYPES:
        return unsupported(document_id, media_type, detail=f"{media_type!r} is not a PDF")
    if not (HAVE_PDFPLUMBER or HAVE_PYMUPDF):
        return AdapterResult(
            document_id=document_id,
            media_type=media_type,
            status="unsupported",
            error="no PDF text backend installed: needs pdfplumber or PyMuPDF",
        )

    def body() -> AdapterResult:
        if HAVE_PDFPLUMBER:
            pages = _pages_with_pdfplumber(data)
            engine = "pdfplumber"
        else:
            pages = _pages_with_pymupdf(data)
            engine = "pymupdf"
        if not pages:
            # A damaged PDF can open with no pages rather than raising. A page with no words
            # on it is a legitimate result (that is what a scan looks like); a file with no
            # pages is a broken file, and the two must not report the same way.
            raise ValueError("no pages could be read: the file is not a readable PDF")

        facts: list[ExtractedFact] = []
        skipped = 0

        def emit(label: str, value: str, box: tuple[float, float, float, float],
                 page_number: int, width: float, height: float, context: str,
                 record_key: str) -> None:
            nonlocal skipped
            try:
                bbox = normalized_bbox(box[0], box[1], box[2], box[3], width, height)
            except ValueError:
                skipped += 1  # a box we cannot vouch for is not provenance
                return
            facts.append(
                ExtractedFact(
                    document_id=document_id,
                    source_label=label,
                    raw_value=value,
                    source_location=SourceLocationPdf(page=page_number, bbox=bbox),
                    record_key=record_key,
                    context=context,
                )
            )

        for number, width, height, words in pages:
            lines = _lines(words)
            table_width = _table_width(lines)
            headings: list[str] | None = None
            # The line index is the record identity for a PDF table: one record per row of
            # the table, scoped to the page, so a page 2 row 3 is not a page 1 row 3.
            for line_index, cells in enumerate(lines):
                record_key = f"p{number}:line:{line_index}"
                is_table_row = table_width is not None and len(cells) == table_width
                if is_table_row and headings is None:
                    headings = [cell[0] for cell in cells]
                    continue
                if is_table_row:
                    context = snippet(" | ".join(cell[0] for cell in cells))
                    for index, cell in enumerate(cells):
                        emit(
                            headings[index], cell[0],
                            (cell[1], cell[2], cell[3], cell[4]),
                            number, width, height, context, record_key,
                        )
                    continue
                text = " ".join(cell[0] for cell in cells)
                emit(
                    UNLABELLED, text, _line_bbox(cells), number, width, height,
                    snippet(text), record_key,
                )

        return AdapterResult(
            document_id=document_id,
            media_type=media_type,
            status="done",
            facts=facts,
            engine=engine,
            page_count=len(pages),
            skipped=skipped,
        )

    return run_contained(document_id, media_type, body)


def extract(
    data: bytes, media_type: str = "application/pdf", *, document_id: str = ""
) -> list[ExtractedFact]:
    """The seam the pipeline calls. Empty on any failure; `extract_document` says why."""
    return extract_document(data, media_type, document_id=document_id).facts


__all__ = [
    "MEDIA_TYPES",
    "HAVE_PDFPLUMBER",
    "HAVE_PYMUPDF",
    "extract",
    "extract_document",
]
