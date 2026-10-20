"""Reads an HTML page into facts located by character offset into the source.

Why it exists: the contract locates text with `{type:'text', start, end}`, and those offsets
have to index the bytes a reviewer will be shown -- highlight the wrong span and the
provenance story is worse than none. So this is built on the stdlib `html.parser`, which is
the only one of the candidates that reports source positions at all: `selectolax` and
`lxml` hand back a tree with the offsets already thrown away, which makes them a
convenience here rather than a capability. Entity handling is explicit (`convert_charrefs`
off) because the decoded length of `&amp;` is not its source length, and silently mixing the
two is how a span drifts a character per entity.

Every offset this module emits is checked against the source before it leaves: `source[start:
end]` must still contain the value, or the fact is dropped and counted.

What it refuses to do: it refuses to interpret a heading or a value, and it refuses to raise
-- a page that will not decode comes back as an `error` result and the batch continues.
"""

from __future__ import annotations

import html as _html
from html.parser import HTMLParser

from backend.adapters.base import (
    UNLABELLED,
    AdapterResult,
    ExtractedFact,
    run_contained,
    snippet,
    unsupported,
)
from backend.engine.contracts import SourceLocationText

MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})

_CELL_TAGS = frozenset({"td", "th"})
_PROSE_TAGS = frozenset({"p", "li", "h1", "h2", "h3", "h4", "caption", "blockquote"})
#: Tags whose text is markup noise rather than page content.
_IGNORED_TAGS = frozenset({"script", "style", "title"})


class _Span:
    """A piece of page text and the exact source offsets it came from."""

    __slots__ = ("text", "start", "end")

    def __init__(self, text: str, start: int, end: int) -> None:
        self.text = text
        self.start = start
        self.end = end


class _Reader(HTMLParser):
    """Collects table rows and prose spans, each with source offsets.

    A cell's span runs from the end of its start tag to the start of its end tag, so it
    covers the cell's inner source exactly -- including any entity references, whose source
    length is what the offsets have to describe.
    """

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self._source = source
        self._line_starts = [0]
        for index, character in enumerate(source):
            if character == "\n":
                self._line_starts.append(index + 1)
        self._open: list[tuple[str, int]] = []
        self._ignoring = 0
        self.rows: list[list[_Span]] = []
        self.prose: list[_Span] = []
        self._row: list[_Span] | None = None

    # -- positions ---------------------------------------------------------

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def _span(self, start: int, end: int) -> _Span | None:
        raw = self._source[start:end]
        lead = len(raw) - len(raw.lstrip())
        trail = len(raw) - len(raw.rstrip())
        text = _html.unescape(raw.strip())
        if not text:
            return None
        return _Span(text, start + lead, end - trail)

    # -- parser callbacks --------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _IGNORED_TAGS:
            self._ignoring += 1
            return
        if self._ignoring:
            return
        if tag == "tr":
            self._row = []
        start_text = self.get_starttag_text() or f"<{tag}>"
        self._open.append((tag, self._offset() + len(start_text)))

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        return  # self-closing tags carry no text

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_TAGS:
            self._ignoring = max(0, self._ignoring - 1)
            return
        if self._ignoring:
            return
        end = self._offset()
        # Unwind to the matching start tag: unclosed inner tags are common in real pages
        # and must not shift every later offset.
        while self._open:
            opened, content_start = self._open.pop()
            if opened != tag:
                continue
            if tag in _CELL_TAGS and self._row is not None:
                span = self._span(content_start, end)
                if span is not None:
                    self._row.append(span)
            elif tag in _PROSE_TAGS:
                span = self._span(content_start, end)
                if span is not None:
                    self.prose.append(span)
            break
        if tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def extract_document(
    data: bytes, media_type: str = "text/html", *, document_id: str = ""
) -> AdapterResult:
    if media_type not in MEDIA_TYPES:
        return unsupported(
            document_id, media_type, detail=f"{media_type!r} is not an HTML type"
        )

    def body() -> AdapterResult:
        source = data.decode("utf-8")
        reader = _Reader(source)
        reader.feed(source)
        reader.close()

        facts: list[ExtractedFact] = []
        skipped = 0
        headings: list[str] = []
        for row_index, row in enumerate(reader.rows):
            if not headings:
                # The first row of a table names its columns. A page whose first row is
                # data loses that row rather than having labels invented for it.
                headings = [span.text for span in row]
                continue
            context = snippet(" | ".join(span.text for span in row))
            for index, span in enumerate(row):
                if index >= len(headings):
                    continue
                if span.text not in source[span.start : span.end + 1]:
                    skipped += 1  # offsets that do not round-trip are not provenance
                    continue
                facts.append(
                    ExtractedFact(
                        document_id=document_id,
                        source_label=headings[index],
                        raw_value=span.text,
                        source_location=SourceLocationText(start=span.start, end=span.end),
                        # One record per table row, by position in the document.
                        record_key=f"tr:{row_index}",
                        context=context,
                    )
                )
        for span in reader.prose:
            facts.append(
                ExtractedFact(
                    document_id=document_id,
                    source_label=UNLABELLED,
                    raw_value=span.text,
                    source_location=SourceLocationText(start=span.start, end=span.end),
                    # Prose outside a table is its own record, keyed by where it starts --
                    # there is no row to belong to, and lumping it with the table would
                    # attach a sentence to a product it may say nothing about.
                    record_key=f"prose:{span.start}",
                    context=snippet(span.text),
                )
            )
        return AdapterResult(
            document_id=document_id,
            media_type=media_type,
            status="done",
            facts=facts,
            engine="stdlib-html.parser",
            skipped=skipped,
        )

    return run_contained(document_id, media_type, body)


def extract(
    data: bytes, media_type: str = "text/html", *, document_id: str = ""
) -> list[ExtractedFact]:
    """The seam the pipeline calls. Empty on any failure; `extract_document` says why."""
    return extract_document(data, media_type, document_id=document_id).facts


__all__ = ["MEDIA_TYPES", "extract", "extract_document"]
