"""Export is a render, not a generation (Law IV). Same data in, byte-identical file out.

Exists because an export that varies between two runs on the same data cannot be used as
evidence, and evidence is what we are selling. There is no model call in this path and
there must never be one.

Everything that could make two identical exports differ is pinned here: column order comes
from the pack's declaration order rather than from dict iteration, rows are sorted by a
stable key, the line terminator is LF on every platform, floats are never reformatted (the
values arrive as strings already rendered by units.py), and no clock is read. If you add a
column, add it to a declared order -- do not append it from a set.

What this module refuses to do:
  * It refuses to put a timestamp in a file whose bytes are compared.
  * It refuses to call a model.
  * It refuses to name a domain field. Column names arrive from the pack (Law II).
"""

from __future__ import annotations

import csv
import io
import json
from typing import Iterable, Sequence

from backend.engine.contracts import Mapping

#: Audit columns, in declared order. Appended after the data columns when audit=True.
AUDIT_COLUMNS: tuple[str, ...] = (
    "_status",
    "_confidence",
    "_source_type",
    "_source_page",
    "_source_bbox",
    "_source_sheet",
    "_source_cell",
    "_source_start",
    "_source_end",
    "_conversion_rule_id",
    "_conversion_factor",
    "_formula_text",
    "_reason",
)


def _location_columns(mapping: Mapping) -> dict[str, str]:
    """Flatten whichever source location this mapping has, leaving the rest empty."""
    blank = {
        "_source_type": "",
        "_source_page": "",
        "_source_bbox": "",
        "_source_sheet": "",
        "_source_cell": "",
        "_source_start": "",
        "_source_end": "",
    }
    location = mapping.source_location
    if location is None:
        return blank
    blank["_source_type"] = location.type
    if location.type == "pdf":
        blank["_source_page"] = str(location.page)
        # Fixed precision so the same box never renders two ways.
        blank["_source_bbox"] = ",".join(f"{n:.6f}" for n in location.bbox)
    elif location.type == "sheet":
        blank["_source_sheet"] = location.sheet
        blank["_source_cell"] = location.cell
    else:
        blank["_source_start"] = str(location.start)
        blank["_source_end"] = str(location.end)
    return blank


def _audit_columns(mapping: Mapping) -> dict[str, str]:
    columns = {
        "_status": mapping.status,
        "_confidence": f"{mapping.confidence:.4f}",
        "_conversion_rule_id": mapping.conversion.rule_id if mapping.conversion else "",
        "_conversion_factor": (
            f"{mapping.conversion.factor:.6f}" if mapping.conversion else ""
        ),
        "_formula_text": mapping.conversion.formula_text if mapping.conversion else "",
        "_reason": mapping.reason or "",
    }
    columns.update(_location_columns(mapping))
    return columns


def to_rows(
    mappings: Iterable[Mapping],
    field_order: Sequence[str],
    *,
    audit: bool = False,
    record_keys: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """One row per RECORD, with columns in the pack's declared order.

    `record_keys` maps a mapping id to which record inside its document it belongs to. A
    document is not a record: a rate sheet holds one record per product row, and grouping
    by document alone produced one row where there were thirty, with the last value
    written winning. Omitting it keeps the old document-level grouping, which is correct
    only for a document that really is a single record.

    A mapping with no target field (the `missing` lane after a refusal) still contributes
    its row, because a missing value is written and shown, never dropped.
    """
    keys = record_keys or {}
    grouped: dict[tuple[str, str], dict[str, Mapping]] = {}
    for mapping in mappings:
        group = (mapping.document_id, keys.get(mapping.id, ""))
        grouped.setdefault(group, {})
        if mapping.target_field:
            grouped[group][mapping.target_field] = mapping

    rows: list[dict[str, str]] = []
    for document_id, record_key in sorted(grouped):
        fields = grouped[(document_id, record_key)]
        row: dict[str, str] = {"document_id": document_id, "record": record_key}
        for field in field_order:
            mapping = fields.get(field)
            row[field] = "" if mapping is None else mapping.value
        if audit:
            # One audit block per row, taken from the first declared field present, so the
            # column set is fixed whatever the data contains.
            anchor = next((fields[f] for f in field_order if f in fields), None)
            if anchor is None:
                row.update({column: "" for column in AUDIT_COLUMNS})
            else:
                row.update(_audit_columns(anchor))
        rows.append(row)
    return rows


def render_csv(
    mappings: Iterable[Mapping],
    field_order: Sequence[str],
    *,
    audit: bool = False,
    record_keys: dict[str, str] | None = None,
) -> bytes:
    """Deterministic CSV. LF terminator on every platform, declared column order."""
    columns = ["document_id", "record", *field_order]
    if audit:
        columns += list(AUDIT_COLUMNS)
    rows = to_rows(mappings, field_order, audit=audit, record_keys=record_keys)

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue().encode("utf-8")


def render_json(
    mappings: Iterable[Mapping],
    field_order: Sequence[str],
    *,
    audit: bool = False,
    record_keys: dict[str, str] | None = None,
) -> bytes:
    """Deterministic JSON. Sorted keys, fixed separators, trailing newline."""
    rows = to_rows(mappings, field_order, audit=audit, record_keys=record_keys)
    text = json.dumps(rows, sort_keys=True, indent=2, separators=(",", ": "), ensure_ascii=False)
    return (text + "\n").encode("utf-8")
