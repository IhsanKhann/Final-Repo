"""Narrative disclosures: prose with figures buried in it, read with exact provenance.

Exists because "narrative disclosures" is one of PS-12's five technical requirements and it
had no adapter at all -- a 5,894-byte disclosure returned zero facts and could not be
ingested. It is also the one document type where the mapper agent earns its place, because
there is no table to parse and no column heading to match: the label has to be recognised
from the sentence around the number.

What this module does, and the line it will not cross: it finds every figure, records the
exact character offsets so a reviewer can be shown the sentence it came from, and offers
the words immediately around it as a candidate label. It does NOT decide what the figure
means. Prose like "pays 3.416% annually on balances over $500" contains two numbers with
different meanings, and distinguishing them is a judgement -- so it goes to the mapper, or
to a pack that declares prose phrasing as synonyms, and never to a guess here (Law II: an
adapter that inferred meaning from English would be meaning living in the wrong layer).

One record per sentence. A disclosure describes one product per sentence or clause, and
lumping a whole file into one record would attach a figure to a product it says nothing
about -- the same collapse that made the gold table a thirtieth of the data.
"""

from __future__ import annotations

import re

from backend.adapters.base import (
    AdapterResult,
    run_contained,
    snippet,
)
from backend.engine.contracts import ExtractedFact, SourceLocationText

MEDIA_TYPES = frozenset({"text/plain", "text/markdown"})

#: A figure as a document prints one: optional currency, digits with optional thousands
#: separators and decimals, optional trailing percent. Symbols, not domain nouns.
#:
#: The thousands group is `(?:,\d{3})*` rather than `[\d,]*` so a trailing sentence comma
#: cannot be swallowed into the value -- "$1,000," was being read as the figure "$1,000,",
#: which is not a number and is not what the document says.
_FIGURE = re.compile(r"[$£€]?\d+(?:,\d{3})*(?:\.\d+)?\s?%?")

#: Dates, matched BEFORE figures and excluded from them. "July 1, 2026" is one value; read
#: as figures it becomes "1" and "2026", two meaningless numbers in the review tray and a
#: date the pack can never resolve.
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_DATE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    rf"|(?:{_MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}}"
    rf"|\d{{1,2}}\s+(?:{_MONTHS})\.?\s+\d{{4}}",
    re.IGNORECASE,
)

#: Sentence boundary: a terminator followed by whitespace. Deliberately simple and
#: deterministic -- an abbreviation will occasionally split a sentence early, which costs a
#: little context and never costs an offset, because offsets come from the original text.
_SENTENCE = re.compile(r"(?<=[.!?;])\s+")

#: Words that carry no labelling information. Generic English only: a domain word here
#: would be meaning in the engine's half of the house.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
        "in", "is", "it", "its", "of", "on", "or", "over", "per", "that", "the", "then",
        "this", "to", "was", "were", "will", "with",
    }
)

#: How many words either side of a figure may form a candidate label.
_LABEL_WORDS = 4

_WORD = re.compile(r"[A-Za-z][A-Za-z'/-]*")


def _candidate_label(sentence: str, start: int, end: int) -> str:
    """The words around a figure, as a label the mapper can arbitrate on.

    Takes the words BEFORE the figure first, because English puts the subject before the
    number ("a term of 12 months"), and falls back to the words after it when there are
    none ("3.416% annually"). Stopwords are dropped so that "for a term of" and "the term
    of" produce the same candidate -- a label that varied with grammar would make the
    precedent for one sentence useless for the next.
    """
    before = [w.group(0).lower() for w in _WORD.finditer(sentence[:start])]
    after = [w.group(0).lower() for w in _WORD.finditer(sentence[end:])]

    def pick(words: list[str], from_end: bool) -> list[str]:
        chosen = [w for w in words if w not in _STOPWORDS]
        if not chosen:
            return []
        return chosen[-_LABEL_WORDS:] if from_end else chosen[:_LABEL_WORDS]

    leading = pick(before, from_end=True)
    if leading:
        return " ".join(leading)
    return " ".join(pick(after, from_end=False))


def extract_document(
    data: bytes, media_type: str = "text/plain", *, document_id: str = ""
) -> AdapterResult:
    """Read a narrative document into facts with exact character offsets."""

    def body() -> AdapterResult:
        if media_type not in MEDIA_TYPES:
            raise ValueError(f"{media_type!r} is not a narrative media type")

        # A disclosure that is not valid UTF-8 is a damaged file, not a document with
        # unusual characters: replacing bytes would shift every offset after the first
        # bad one, and an offset we cannot trust is not provenance.
        source = data.decode("utf-8")

        facts: list[ExtractedFact] = []
        skipped = 0
        offset = 0
        sentence_index = 0

        for piece in _SENTENCE.split(source):
            # Locate the sentence in the ORIGINAL text rather than reconstructing it, so
            # the offsets below are offsets into the file the reviewer will be shown.
            found = source.find(piece, offset)
            if found == -1:
                skipped += 1
                continue
            offset = found + len(piece)
            if not piece.strip():
                continue

            record_key = f"sentence:{sentence_index}"
            sentence_index += 1
            context = snippet(piece)

            # Dates first, and their spans then block figure matches inside them.
            dates = list(_DATE.finditer(piece))
            claimed = [(m.start(), m.end()) for m in dates]
            candidates = list(dates)
            for figure in _FIGURE.finditer(piece):
                inside = any(s <= figure.start() < e for s, e in claimed)
                if not inside:
                    candidates.append(figure)

            for match in sorted(candidates, key=lambda m: m.start()):
                text = match.group(0)
                raw = text.strip().rstrip(",")
                if not any(ch.isdigit() for ch in raw):
                    continue
                start = found + match.start()
                end = start + len(raw)
                if source[start:end] != raw:
                    skipped += 1  # an offset that does not round-trip is not provenance
                    continue

                facts.append(
                    ExtractedFact(
                        document_id=document_id,
                        source_label=_candidate_label(piece, match.start(), match.end()),
                        raw_value=raw,
                        source_location=SourceLocationText(start=start, end=end),
                        record_key=record_key,
                        context=context,
                    )
                )

        return AdapterResult(
            document_id=document_id,
            media_type=media_type,
            status="done",
            facts=facts,
            engine="stdlib-re",
            skipped=skipped,
        )

    return run_contained(document_id, media_type, body)


def extract(
    data: bytes, media_type: str = "text/plain", *, document_id: str = ""
) -> list[ExtractedFact]:
    """The seam the pipeline calls. Empty on any failure; `extract_document` says why."""
    return extract_document(data, media_type, document_id=document_id).facts


__all__ = ["MEDIA_TYPES", "extract", "extract_document"]
