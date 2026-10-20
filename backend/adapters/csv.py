"""Reads a delimited text file into facts addressed like spreadsheet cells.

Why it exists: a CSV has no cells, only lines, but the contract's provenance for tabular
data is `{type:'sheet', sheet, cell}` and a reviewer needs to be told where to look. So the
header row is row 1 and the first data row is row 2, exactly as every spreadsheet
application shows the same file.

What it refuses to do: it refuses to interpret. A heading is an opaque string, a cell's text
is passed through byte for byte, and no unit is split off a value here -- the pack declares
what a column means and the engine converts it. It also refuses to raise: an undecodable or
ragged file comes back as an `error` result so the rest of the batch still runs.
"""

from __future__ import annotations

import csv as _stdlib_csv
import io

from backend.adapters.base import (
    AdapterResult,
    ExtractedFact,
    cell_ref,
    run_contained,
    snippet,
    unsupported,
)
from backend.engine.contracts import SourceLocationSheet

MEDIA_TYPES = frozenset({"text/csv", "application/csv", "text/tab-separated-values"})

#: The contract's `sheet` field has to say something, and a CSV has no sheet name. A fixed
#: literal keeps the source location round-trippable without inventing a name from the
#: filename.
SHEET_NAME = "csv"

try:  # pandas is the lane's declared library; the stdlib reader is the honest fallback.
    import pandas as _pandas

    HAVE_PANDAS = True
except ImportError:  # pragma: no cover - exercised only on a host without pandas
    _pandas = None
    HAVE_PANDAS = False


def _grid_with_pandas(text: str) -> tuple[list[str], list[list[str]]]:
    frame = _pandas.read_csv(
        io.StringIO(text), dtype=str, keep_default_na=False, na_filter=False
    )
    headers = [str(column) for column in frame.columns]
    rows = [[str(value) for value in record] for record in frame.itertuples(index=False)]
    return headers, rows


def _grid_with_stdlib(text: str) -> tuple[list[str], list[list[str]]]:
    reader = _stdlib_csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        return [], []
    return headers, [row for row in reader]


def extract_document(
    data: bytes, media_type: str = "text/csv", *, document_id: str = ""
) -> AdapterResult:
    if media_type not in MEDIA_TYPES:
        return unsupported(
            document_id, media_type, detail=f"{media_type!r} is not a delimited text type"
        )

    def body() -> AdapterResult:
        # Strict decode on purpose: a file that is not text is a file we must report, not
        # one we should silently mangle with replacement characters.
        text = data.decode("utf-8-sig")
        if HAVE_PANDAS:
            headers, rows = _grid_with_pandas(text)
            engine = "pandas"
        else:
            headers, rows = _grid_with_stdlib(text)
            engine = "stdlib-csv"

        facts: list[ExtractedFact] = []
        for row_offset, row in enumerate(rows):
            context = snippet(" | ".join(row))
            for column_index, value in enumerate(row):
                if column_index >= len(headers) or value == "":
                    continue
                facts.append(
                    ExtractedFact(
                        document_id=document_id,
                        source_label=headers[column_index],
                        raw_value=value,
                        source_location=SourceLocationSheet(
                            sheet=SHEET_NAME,
                            # +2: row 1 is the heading row, and spreadsheets count from 1.
                            cell=cell_ref(column_index, row_offset + 2),
                        ),
                        # One record per data row. A file holds many records and the row
                        # number is the document's own identity for them.
                        record_key=f"row:{row_offset + 2}",
                        context=context,
                    )
                )
        return AdapterResult(
            document_id=document_id,
            media_type=media_type,
            status="done",
            facts=facts,
            engine=engine,
        )

    return run_contained(document_id, media_type, body)


def extract(
    data: bytes, media_type: str = "text/csv", *, document_id: str = ""
) -> list[ExtractedFact]:
    """The seam the pipeline calls. Empty on any failure; `extract_document` says why."""
    return extract_document(data, media_type, document_id=document_id).facts


__all__ = ["MEDIA_TYPES", "SHEET_NAME", "HAVE_PANDAS", "extract", "extract_document"]
