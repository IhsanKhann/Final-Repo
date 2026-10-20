"""Format adapters: bytes in, `ExtractedFact[]` out, one module per format, no shared state.

Each module exposes the same pair. `extract(data, media_type, *, document_id=...)` is the
seam the pipeline calls and returns facts only. `extract_document(...)` returns an
`AdapterResult` carrying the status, the parser's own error message and which backend ran --
because a corrupt file has to mark that document and let the batch continue, which means the
failure needs somewhere to be reported rather than raised (CLAUDE.md section 6).

This package is domain-blind by law: a column heading is an opaque string, no module here
names a field, a unit or an institution, and no value is interpreted, split or converted on
the way through. Meaning is declared in a pack and applied by the engine (Law II).

Dispatch below maps a media type to the deterministic first choice for it. PDFs go to
`pdf_text`; choosing `pdf_scan` instead is the pipeline's decision, taken when a PDF turns
out to have no text layer, and is deliberately not a heuristic buried in here.
"""

from __future__ import annotations

from typing import Callable

from backend.adapters import csv, html, narrative, pdf_scan, pdf_text, sheet
from backend.adapters.base import AdapterResult, unsupported

#: media type -> the module that reads it. One entry per media type, not per format, so a
#: caller never has to guess which module owns a mime string.
ADAPTERS: dict[str, Callable[..., AdapterResult]] = {
    **{media_type: csv.extract_document for media_type in csv.MEDIA_TYPES},
    **{media_type: sheet.extract_document for media_type in sheet.MEDIA_TYPES},
    **{media_type: html.extract_document for media_type in html.MEDIA_TYPES},
    **{media_type: pdf_text.extract_document for media_type in pdf_text.MEDIA_TYPES},
    # Narrative disclosures: the fifth technical requirement, and the one document
    # type where the mapper agent earns its place -- there is no heading to match.
    **{media_type: narrative.extract_document for media_type in narrative.MEDIA_TYPES},
}


def extract_document(
    data: bytes, media_type: str, *, document_id: str = ""
) -> AdapterResult:
    """Dispatch on media type. An unknown type is `unsupported`, which is not an error."""
    adapter = ADAPTERS.get(media_type)
    if adapter is None:
        return unsupported(
            document_id, media_type, detail=f"no adapter registered for {media_type!r}"
        )
    return adapter(data, media_type, document_id=document_id)


__all__ = [
    "ADAPTERS",
    "AdapterResult",
    "extract_document",
    "csv",
    "html",
    "pdf_scan",
    "pdf_text",
    "sheet",
]
