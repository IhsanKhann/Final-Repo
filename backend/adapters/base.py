"""Shared plumbing for the format adapters: a typed result, and the bbox division.

Why it exists: every adapter needs the same three things -- a way to report failure without
raising across its seam, a way to address a cell, and the one place where absolute page
coordinates become the normalized 0-1 box the contract demands. Having three copies of the
division is how one of them ends up undivided in the UI.

What it refuses to do:

* It refuses to raise. `run_contained` turns any parser explosion into a result with a
  status and the parser's own message, because one corrupt file must mark that document and
  leave the batch running (CLAUDE.md section 6).
* It refuses to know what anything means. A column heading is an opaque string here; no
  adapter under this package may name a field, a unit or an institution (Law II). Nothing
  in this module interprets a value, splits a unit off it, or decides what it is -- the pack
  declares meaning and the engine applies it.
* It refuses to emit a box it has not checked. `normalized_bbox` validates before
  `SourceLocationPdf` ever sees the numbers, so a library that returns points cannot leak
  points downstream.
"""

from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.engine.contracts import ExtractedFact, Unavailable

#: `done` -- parsed. `unsupported` -- we do not read this media type, and saying so is not an
#: error. `error` -- the file is this media type and would not parse. `unavailable` -- the
#: file is fine but a dependency of the extraction is not, which sends the document to
#: review rather than marking it broken.
AdapterStatus = Literal["done", "unsupported", "error", "unavailable"]

#: A fact with no heading above it: a footnote, a title, a sentence. The empty string is
#: deliberate -- inventing a label here would be the adapter guessing, and a downstream
#: extractor agent is the thing allowed to label prose.
UNLABELLED = ""

#: How far outside the page box a coordinate may stray before it stops being a glyph
#: overhang and starts being a sign we divided by the wrong number.
_BBOX_SLACK = 0.01


class AdapterResult(BaseModel):
    """What an adapter returns instead of raising.

    `facts` is always present and always valid; on any non-`done` status it is empty, so a
    caller that ignores `status` under-reports rather than ingesting garbage.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: str
    media_type: str
    status: AdapterStatus
    facts: list[ExtractedFact] = Field(default_factory=list)
    #: Which library actually did the reading. Recorded because two of these modules have
    #: two possible backends and "it worked on my machine" is otherwise unfalsifiable.
    engine: str | None = None
    error: str | None = None
    #: Set only when status is `unavailable`; carries the same named reasons the
    #: intelligence layer uses, so a missing vision backend and a missing model key read
    #: identically to the review tray.
    unavailable: Unavailable | None = None
    page_count: int | None = None
    #: Values found but not emitted, because their provenance would not validate. Counted
    #: rather than logged: a silent drop is indistinguishable from an empty document.
    skipped: int = 0


def unsupported(document_id: str, media_type: str, *, detail: str) -> AdapterResult:
    return AdapterResult(
        document_id=document_id, media_type=media_type, status="unsupported", error=detail
    )


def run_contained(
    document_id: str, media_type: str, body: Callable[[], AdapterResult]
) -> AdapterResult:
    """Call `body`, converting any exception into an `error` result.

    Broad on purpose: parser libraries raise their own hierarchies plus `struct.error`,
    `zlib.error`, `KeyError` and bare `Exception`, and enumerating them would mean the next
    unlisted one kills the batch.
    """
    try:
        return body()
    except Exception as exc:  # noqa: BLE001 -- see docstring
        return AdapterResult(
            document_id=document_id,
            media_type=media_type,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
        )


def column_letter(index_zero_based: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    if index_zero_based < 0:
        raise ValueError(f"column index must not be negative, got {index_zero_based}")
    letters = ""
    n = index_zero_based + 1
    while n:
        n, remainder = divmod(n - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def cell_ref(column_zero_based: int, row_one_based: int) -> str:
    """(1, 12) -> "B12". Rows are 1-based because that is what a spreadsheet shows."""
    if row_one_based < 1:
        raise ValueError(f"row must be 1-based, got {row_one_based}")
    return f"{column_letter(column_zero_based)}{row_one_based}"


def normalized_bbox(
    x0: float, y0: float, x1: float, y1: float, page_width: float, page_height: float
) -> tuple[float, float, float, float]:
    """Absolute points -> normalized `[x, y, w, h]`. The only division in the codebase.

    Note the shape change: libraries hand back two corners, the contract wants an origin
    plus a width and a height. Dividing all four corners and calling it a bbox is the bug
    this function exists to make impossible.
    """
    if page_width <= 0 or page_height <= 0:
        raise ValueError(f"page size must be positive, got {page_width}x{page_height}")
    left, right = (x0, x1) if x1 >= x0 else (x1, x0)
    top, bottom = (y0, y1) if y1 >= y0 else (y1, y0)
    box = (
        left / page_width,
        top / page_height,
        (right - left) / page_width,
        (bottom - top) / page_height,
    )
    clamped = []
    for value in box:
        if value < -_BBOX_SLACK or value > 1.0 + _BBOX_SLACK:
            raise ValueError(
                f"bbox {box!r} is not within 0-1 for a {page_width}x{page_height} page: "
                "the coordinates were probably divided by the wrong page"
            )
        clamped.append(min(1.0, max(0.0, value)))
    return (clamped[0], clamped[1], clamped[2], clamped[3])


def snippet(text: str, limit: int = 240) -> str:
    """Context for a reviewer and for the verifier agent. Collapsed, never reinterpreted."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


__all__ = [
    "AdapterResult",
    "AdapterStatus",
    "UNLABELLED",
    "cell_ref",
    "column_letter",
    "normalized_bbox",
    "run_contained",
    "snippet",
    "unsupported",
    "ExtractedFact",
]
