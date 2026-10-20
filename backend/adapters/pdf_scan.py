"""Reads a PDF with no text layer: rasterize here, read the pixels elsewhere.

Why it exists as its own module with one signature: `extract(data, media_type)` is the seam
Google Document AI swaps in behind. Everything that is ours -- opening the file, turning
pages into images, validating boxes, building facts -- stays; the step that reads pixels is a
parameter. Adding Document AI later changes this module body and no signature anywhere else,
which is the only reason deferring it is safe (CLAUDE.md section 6b).

The reading step is injected, and its default returns `Unavailable`, not an empty list and
certainly not a guess. That is why this module imports with no key, no SDK and no network:
nothing here constructs a client, and nothing at import time reaches anywhere. A document
whose pixels could not be read comes back `unavailable` with a named reason, which means the
review tray -- the same path a provider outage takes. An `Unavailable` never means zero
facts were found; it means we do not know, and the difference is the product.

Rasterization is PyMuPDF, deliberately: poppler/pdf2image needs a system binary that does
not install cleanly on Windows, and this had to run on the machine it was demoed from.

What it refuses to do: it refuses to return a partial page set -- if any page cannot be read,
the whole document is `unavailable`, because a scan missing a silent third of its rows looks
exactly like a scan that only had two thirds. It refuses to trust a box it was handed: a
vision backend returning absolute pixels instead of normalized coordinates has those facts
dropped and counted, not reshaped into something plausible.
"""

from __future__ import annotations

from typing import Callable, Union

from pydantic import BaseModel, ConfigDict, Field

from backend.adapters.base import (
    UNLABELLED,
    AdapterResult,
    ExtractedFact,
    run_contained,
    unsupported,
)
from backend.engine.contracts import SourceLocationPdf, Unavailable

MEDIA_TYPES = frozenset({"application/pdf"})

#: 200 dpi: enough for small print to survive, small enough to stay inside a per-document
#: token budget once the image is handed to a model.
DEFAULT_DPI = 200

try:
    import fitz as _fitz

    HAVE_PYMUPDF = True
except ImportError:  # pragma: no cover - exercised only on a host without PyMuPDF
    _fitz = None
    HAVE_PYMUPDF = False


class ScanPage(BaseModel):
    """One rasterized page, as handed to whatever reads pixels."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    image_png: bytes
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    dpi: int = Field(gt=0)


class VisionCell(BaseModel):
    """One value a vision backend claims to have read off a page.

    `bbox` is NORMALIZED 0-1 `[x, y, w, h]`, in the page's own coordinate space and not in
    pixels: the backend sees an image whose size it is told, so converting is its job and
    checking is ours.
    """

    model_config = ConfigDict(extra="forbid")

    raw_value: str
    source_label: str = UNLABELLED
    bbox: tuple[float, float, float, float]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    context: str | None = None


VisionOutcome = Union[list[VisionCell], Unavailable]
VisionFn = Callable[[ScanPage], VisionOutcome]


def no_vision_configured(page: ScanPage) -> Unavailable:
    """The default reader. Says it cannot see rather than returning nothing.

    `no-key` is the honest reason: the page was rasterized successfully and there is simply
    no configured backend to read it with.
    """
    return Unavailable(
        reason="no-key",
        detail=(
            f"page {page.page} was rasterized at {page.dpi} dpi but no vision backend was "
            "supplied to pdf_scan.extract"
        ),
    )


def _rasterize(data: bytes, dpi: int) -> list[ScanPage]:
    document = _fitz.open(stream=data, filetype="pdf")
    try:
        pages: list[ScanPage] = []
        for number, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(dpi=dpi)
            pages.append(
                ScanPage(
                    page=number,
                    image_png=pixmap.tobytes("png"),
                    width_px=pixmap.width,
                    height_px=pixmap.height,
                    dpi=dpi,
                )
            )
        return pages
    finally:
        document.close()


def extract_document(
    data: bytes,
    media_type: str = "application/pdf",
    *,
    document_id: str = "",
    vision: VisionFn | None = None,
    dpi: int = DEFAULT_DPI,
) -> AdapterResult:
    if media_type not in MEDIA_TYPES:
        return unsupported(document_id, media_type, detail=f"{media_type!r} is not a PDF")
    if not HAVE_PYMUPDF:
        return AdapterResult(
            document_id=document_id,
            media_type=media_type,
            status="unsupported",
            error="no rasterizer installed: needs PyMuPDF",
        )
    read_page = no_vision_configured if vision is None else vision

    def body() -> AdapterResult:
        pages = _rasterize(data, dpi)
        if not pages:
            # A damaged PDF can open with no pages at all rather than raising. Without this
            # it would read as a document that was processed and simply had nothing on it,
            # which is the one failure mode error containment is supposed to make visible.
            raise ValueError("no pages could be rasterized: the file is not a readable PDF")
        facts: list[ExtractedFact] = []
        skipped = 0
        for page in pages:
            outcome = read_page(page)
            if isinstance(outcome, Unavailable):
                return AdapterResult(
                    document_id=document_id,
                    media_type=media_type,
                    status="unavailable",
                    engine="pymupdf+vision",
                    unavailable=outcome,
                    page_count=len(pages),
                )
            for cell in outcome:
                try:
                    location = SourceLocationPdf(page=page.page, bbox=cell.bbox)
                except ValueError:
                    # The contract's own validator caught it. Dropped and counted: a box in
                    # pixels is not a box we can show, and rescaling it would be us
                    # inventing provenance on a model's behalf.
                    skipped += 1
                    continue
                facts.append(
                    ExtractedFact(
                        document_id=document_id,
                        source_label=cell.source_label,
                        raw_value=cell.raw_value,
                        source_location=location,
                        # Banded by the box's vertical position, because a vision reading
                        # has no row numbers to report: cells printed on the same line of
                        # the page share a y and so belong to the same record. Rounded so
                        # the banding is deterministic rather than float-noise sensitive.
                        record_key=f"p{page.page}:y:{round(cell.bbox[1], 3)}",
                        extractor_confidence=cell.confidence,
                        context=cell.context,
                    )
                )
        return AdapterResult(
            document_id=document_id,
            media_type=media_type,
            status="done",
            facts=facts,
            engine="pymupdf+vision",
            page_count=len(pages),
            skipped=skipped,
        )

    return run_contained(document_id, media_type, body)


def extract(
    data: bytes,
    media_type: str = "application/pdf",
    *,
    document_id: str = "",
    vision: VisionFn | None = None,
    dpi: int = DEFAULT_DPI,
) -> list[ExtractedFact]:
    """`(bytes, media_type) -> ExtractedFact[]`: the signature Document AI swaps in behind.

    Empty when the pixels could not be read; `extract_document` carries the named reason.
    """
    return extract_document(
        data, media_type, document_id=document_id, vision=vision, dpi=dpi
    ).facts


__all__ = [
    "MEDIA_TYPES",
    "DEFAULT_DPI",
    "HAVE_PYMUPDF",
    "ScanPage",
    "VisionCell",
    "VisionFn",
    "VisionOutcome",
    "no_vision_configured",
    "extract",
    "extract_document",
]
