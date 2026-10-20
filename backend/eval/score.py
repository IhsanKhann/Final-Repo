"""Scores a run against the hand-labelled golden set, or refuses to score it at all.

Exists because two of the four evaluation criteria are numbers -- field mapping accuracy
and unit conversion correctness -- and a number computed against unconfirmed labels is not
a measurement, it is our own guess marking its own homework. The golden set's
`expected_field` is PROPOSED until a human puts their initials in `confirmed_by`.

So the refusal below is not defensive programming, it is the feature. With fewer than the
required confirmed rows this module returns Unscoreable, names how many are confirmed, and
produces no accuracy figure for anyone to quote by accident.

Two decisions worth knowing before you read a number this produces:

  * A confirmed row the pipeline produced NO mapping for counts as WRONG, not as absent.
    The denominator is confirmed rows, never matched rows. Scoring only what we managed to
    emit would make accuracy rise every time coverage fell, which is exactly backwards.
  * (document, source_label) is NOT a key. Measured on the real run, one document and one
    heading identify up to 30 mappings, because every generated document reports all six
    product types under the same headings. The key therefore carries the value as printed
    as well, and where even that still names several mappings the match is REFUSED unless
    they all agree about where the value belongs. See the note on MatchKey.

What this module refuses to do: call a model; report a number it cannot stand behind; and
pick one of several mappings a key cannot tell apart. The last is the newest of the three
and the easiest to get wrong, because guessing there produces a plausible number.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Sequence

from pydantic import BaseModel, ConfigDict

from backend.engine.contracts import Mapping
from backend.engine.units import parse_numeric

#: Agreed in AGREEMENTS section 6: 30 rows, confirmed by initials in `confirmed_by`.
MINIMUM_CONFIRMED_ROWS = 30

#: Tolerance for a converted value, and the reason it is not tighter.
#:
#: The x12 case cannot round-trip exactly. The generated monthly quote is printed to four
#: decimals (that is what a rate sheet prints), so recovering the annual figure multiplies
#: a rounded number: the error is bounded by 12 x 0.00005 = 0.0006 percentage points. A
#: tolerance of 0.0001 would therefore fail every single monthly row while the converter
#: was working perfectly -- which is worse than useless, because the obvious fix for a
#: red conversion test is to loosen it until it passes and stop looking.
#:
#: So this is 0.001: comfortably above the printing bound, and still two orders of
#: magnitude below the gap between any two distinct values in the data.
VALUE_TOLERANCE = Decimal("0.001")

#: Date formats the generated documents actually print, per institution. The scorer
#: compares dates as dates, because "07/01/2026", "01 Jul 2026", "July 1, 2026" and
#: "2026-07-01" are the same day and a string comparison would score three of them wrong
#: while the pipeline was right.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y/%m/%d",
)


def default_golden_set_path() -> Path:
    return Path(__file__).resolve().parent / "golden_set.csv"


class GoldenRow(BaseModel):
    """One hand-labelled expectation. `confirmed_by` is what makes it scoreable."""

    model_config = ConfigDict(extra="forbid")

    gold_id: str
    institution_name: str
    #: The document the pipeline actually ingests, as make_documents.py wrote it. THIS is
    #: the join key. It is not the same thing as the ps06 filename below, and conflating
    #: the two scored 0 matches against a working pipeline -- see default_match_key.
    document_file: str
    #: ps06's own source_file, kept as provenance only. Never joined on.
    ps06_source_file: str = ""
    document_format: str
    product_type: str
    source_label: str
    value_as_printed: str
    expected_field: str
    expected_value: str
    expected_unit: str
    conversion_expected: str
    difficulty: str
    confirmed_by: str = ""

    @property
    def is_confirmed(self) -> bool:
        return bool(self.confirmed_by.strip())

    @property
    def needs_conversion(self) -> bool:
        return self.conversion_expected.strip().lower() not in ("", "none")


#: How a golden row is matched to a produced mapping. Injectable because the correct key
#: depends on how the adapters name a label on a multi-row table, which is an integration
#: agreement rather than a property of scoring.
#:
#: ⚠ THE KEY HAS THREE PARTS AND EVERY ONE OF THEM WAS A BUG FIRST.
#:
#: 1. THE DOCUMENT. The golden set's `ps06_source_file` holds names like
#:    `first_national_bank_rates_page1.pdf` -- the ORIGINAL rate sheets the sample CSV was
#:    derived from. Nothing by that name is ever ingested, and nothing by that name is on
#:    disk. `document_file` names what make_documents.py wrote and the pipeline reads, and
#:    that is the only name joined on. The produced side had the matching half of the same
#:    bug: it keyed on `Mapping.document_id`, which is a fresh uuid (`doc-ab12cd34ef56`).
#:    A filename and a uuid cannot intersect, so `matched` came back 0 for every row and
#:    accuracy read 0.0 while the pipeline was mapping correctly -- the worst shape of
#:    defect, because the number looks like catastrophic failure rather than a broken
#:    join. A `Mapping` does not carry its document's name, so the name has to be supplied:
#:    see `mapping_key_for`.
#:
#: 2. THE LABEL. Necessary and nowhere near sufficient. Measured on the real run,
#:    (document, label) identified 19, 26 or 30 mappings for the 30 golden rows, because
#:    every generated document reports all six product types under one set of headings.
#:
#: 3. THE VALUE AS PRINTED, canonicalised. This is what makes the key a key. It is also
#:    the part that cannot be dropped without the SECOND defect returning silently:
#:    `mapping_accuracy` would still look fine, because all 26 of a column's mappings
#:    resolve to the same field, while `conversion_correctness` would compare the golden
#:    row's expected value against whichever of 26 different rates happened to be first.
#:    A green mapping figure beside a coin-flip conversion figure is worse than two red
#:    ones, because one of them reads as evidence.
#:
#: WHY NOT `Mapping.record_key`, WHICH WOULD IDENTIFY THE RECORD EXACTLY: because a golden
#: row cannot be joined to one. The adapters mint POSITIONAL keys from the rendered
#: document -- `p1:line:3`, `Rates!row:2`, `tr:1`, `sentence:1` -- and nothing in the
#: golden set or in the generator's sidecar records which product sits at which position.
#: Measured, a golden row's `product_type` could only reach a record key by restating five
#: separate layout formulas (`p{page}:line:{3 + i}` for the text PDFs, where the 3 is the
#: renderer's title and header lines; `Rates!row:{2 + i}`; `tr:{1 + i}`;
#: `sentence:{1 + i}`) in a file that cannot check any of them -- and there is no formula
#: at all for the scanned PDF, which yields 0 records today. Worse, the failure mode of a
#: stale formula is a match against the WRONG record, which produces a plausible number.
#: So the record is identified by the value the golden row says was printed, and where
#: that is not unique the match is refused rather than guessed. The honest column would be
#: `expected_record_key`, and it becomes possible only once an adapter records which
#: record it put at which position -- a change in `adapters/`, not in the CSV.
MatchKey = Callable[[GoldenRow], tuple[str, ...]]
MappingKey = Callable[[Mapping], tuple[str, ...]]


def canonical_value(text: str | None) -> str:
    """One spelling per quantity, so two sides of a join can be compared at all.

    `$1,000`, `1000` and `1000.00` are one value; `01 Aug 2026` and `2026-08-01` are one
    day. Dates are tried BEFORE numbers deliberately: `parse_numeric("01 Aug 2026")`
    returns 1, so a number-first canonicaliser would file an August date under the same
    key as a one-month term.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    as_date = _as_date(raw)
    if as_date is not None:
        return as_date.isoformat()
    number = parse_numeric(raw)
    if number is not None:
        return format(number.normalize(), "f")
    return raw.casefold()


def default_match_key(row: GoldenRow) -> tuple[str, ...]:
    """(the document the pipeline reads, the heading, the value as printed)."""
    return (
        row.document_file.strip().casefold(),
        row.source_label.strip().casefold(),
        canonical_value(row.value_as_printed),
    )


def mapping_key_for(document_names: dict[str, str] | None = None) -> MappingKey:
    """The produced-side key, given document_id -> filename.

    The name has to come from outside: `Mapping` carries `document_id`, and the contract in
    types.ts says it carries nothing else about its document. A missing id falls back to
    the id itself, which simply fails to match -- an unresolvable document must not raise
    in the middle of a measurement, and must not match something either.
    """
    names = dict(document_names or {})

    def key(mapping: Mapping) -> tuple[str, ...]:
        name = names.get(mapping.document_id, mapping.document_id)
        return (
            name.strip().casefold(),
            mapping.source_label.strip().casefold(),
            canonical_value(mapping.raw_value),
        )

    return key


#: The key with no document names known, which is what a unit test's fixture supplies when
#: it sets `document_id` to the filename itself. Production passes `document_names`.
default_mapping_key = mapping_key_for()


def _scored_signature(mapping: Mapping) -> tuple[str, str, str]:
    """Everything about a mapping that this module scores, and nothing else.

    Two mappings with the same signature are interchangeable AS FAR AS A SCORE GOES, so
    choosing between them is not a choice. Two with different signatures are not, and
    picking one would be this module inventing which record a golden row meant.
    """
    return (
        mapping.target_field,
        canonical_value(mapping.value),
        (mapping.unit or "").strip().casefold(),
    )


class Unscoreable(BaseModel):
    """Not a score. Returned instead of one, so there is no number to misquote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scoreable: bool = False
    confirmed: int
    required: int
    total_rows: int
    reason: str


class FieldOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gold_id: str
    expected_field: str
    produced_field: str | None
    field_correct: bool
    expected_value: str
    produced_value: str | None
    value_correct: bool | None = None
    conversion_was_expected: bool = False
    #: How many produced mappings the key matched. 1 is the healthy case. More than 1 is
    #: scoreable only because they all say the same thing; it is recorded so a reader can
    #: see how precise the join actually was rather than taking the total on trust.
    candidates: int = 0
    note: str | None = None


class Score(BaseModel):
    """A measurement, with its denominators visible so it cannot be quoted out of shape."""

    model_config = ConfigDict(extra="forbid")

    scoreable: bool = True
    confirmed: int
    #: Correct field / confirmed rows. An unmatched row counts against us.
    mapping_accuracy: float
    #: Correct converted value / confirmed rows that expected a conversion.
    conversion_correctness: float
    conversion_rows: int
    matched: int
    unmatched: int
    #: Rows the key matched several mappings for that did NOT agree about where the value
    #: belongs. Refused rather than scored, and counted in `unmatched` -- so they count as
    #: wrong, like any other row the run cannot account for. Reported separately because
    #: "we cannot tell which record you meant" and "we produced nothing" need different
    #: fixes: the first is a key or an adapter, the second is coverage.
    ambiguous: int = 0
    outcomes: list[FieldOutcome]

    @property
    def complete(self) -> bool:
        return self.unmatched == 0


def load_golden_set(path: str | Path | None = None) -> list[GoldenRow]:
    """Read the golden set. Refuses a row with an unexpected column rather than ignoring it."""
    target = Path(path) if path else default_golden_set_path()
    with target.open(encoding="utf-8", newline="") as handle:
        return [GoldenRow.model_validate(raw) for raw in csv.DictReader(handle)]


def confirmed_rows(rows: Iterable[GoldenRow]) -> list[GoldenRow]:
    return [row for row in rows if row.is_confirmed]


def _as_date(text: str) -> date | None:
    candidate = text.strip()
    if not candidate:
        return None
    for pattern in _DATE_FORMATS:
        try:
            return datetime.strptime(candidate, pattern).date()
        except ValueError:
            continue
    return None


def _values_agree(produced: str | None, expected: str) -> bool:
    """Compare as dates if both are dates, as numbers if both are numbers, else as text.

    Never as raw strings first: the fixtures deliberately print the same quantity in each
    institution's own house style, which is the problem the product solves. Scoring that
    as a mismatch would mark the pipeline wrong for being right.

    Dates come first because `parse_numeric` is not date-aware: it reads "01 Aug 2026" as
    1 and "01 Sep 2026" as 1, so a number-first comparison called two different days
    equal. That is a false CORRECT, which is the one direction a scorer must never err in.
    """
    if produced is None:
        return False

    left_date = _as_date(produced)
    right_date = _as_date(expected)
    if left_date is not None and right_date is not None:
        return left_date == right_date

    left = parse_numeric(produced)
    right = parse_numeric(expected)
    if left is not None and right is not None:
        return abs(left - right) <= VALUE_TOLERANCE

    return produced.strip().casefold() == expected.strip().casefold()


def score(
    mappings: Sequence[Mapping],
    rows: Sequence[GoldenRow] | None = None,
    *,
    minimum_confirmed: int = MINIMUM_CONFIRMED_ROWS,
    document_names: dict[str, str] | None = None,
    match_key: MatchKey = default_match_key,
    mapping_key: MappingKey | None = None,
) -> Score | Unscoreable:
    """Measure a run, or refuse: for want of confirmed labels, or for want of a record.

    `document_names` maps `Mapping.document_id` to the filename the pipeline ingested,
    because that is the half of the key a `Mapping` does not carry. Omit it only where the
    fixture puts the filename in `document_id` itself.

    `mapping_key` overrides the produced-side key entirely; passing both it and
    `document_names` is a contradiction rather than a preference, so it raises here
    instead of quietly ignoring one of them.
    """
    if mapping_key is not None and document_names is not None:
        raise ValueError(
            "pass document_names or mapping_key, not both: a custom mapping_key decides "
            "for itself how a document is named, so the names would be ignored"
        )
    mapping_key = mapping_key or mapping_key_for(document_names)
    rows = list(rows) if rows is not None else load_golden_set()
    confirmed = confirmed_rows(rows)

    if len(confirmed) < minimum_confirmed:
        return Unscoreable(
            confirmed=len(confirmed),
            required=minimum_confirmed,
            total_rows=len(rows),
            reason=(
                f"{len(confirmed)} of {len(rows)} golden rows are confirmed; "
                f"{minimum_confirmed} are required. Every expected_field is still PROPOSED, "
                "so any accuracy figure would be this system grading its own proposal. "
                "Put confirming initials in confirmed_by and re-run."
            ),
        )

    # Every mapping a key matches, not the first one. The previous `setdefault` kept one
    # of 26 and discarded the rest, which is how a conversion figure became a coin flip.
    produced: dict[tuple[str, ...], list[Mapping]] = {}
    for mapping in mappings:
        produced.setdefault(mapping_key(mapping), []).append(mapping)

    outcomes: list[FieldOutcome] = []
    field_correct = 0
    conversion_rows = 0
    conversion_correct = 0
    matched = 0
    ambiguous = 0

    for row in confirmed:
        candidates = produced.get(match_key(row), [])
        interchangeable = {_scored_signature(candidate) for candidate in candidates}

        if not candidates or len(interchangeable) > 1:
            note = "the pipeline produced no mapping for this row, which counts as wrong"
            if candidates:
                ambiguous += 1
                note = (
                    f"{len(candidates)} mappings share this row's key and disagree about "
                    "where the value belongs, so nothing here says which record the row "
                    "meant; refused and counted wrong rather than guessed"
                )
            outcomes.append(
                FieldOutcome(
                    gold_id=row.gold_id,
                    expected_field=row.expected_field,
                    produced_field=None,
                    field_correct=False,
                    expected_value=row.expected_value,
                    produced_value=None,
                    conversion_was_expected=row.needs_conversion,
                    candidates=len(candidates),
                    note=note,
                )
            )
            if row.needs_conversion:
                conversion_rows += 1
            continue

        # Several candidates are fine ONLY here, where they are indistinguishable in
        # every respect this module scores, so there is no choice left to get wrong.
        mapping = candidates[0]
        matched += 1
        correct_field = mapping.target_field == row.expected_field
        field_correct += int(correct_field)

        value_correct: bool | None = None
        if row.needs_conversion:
            conversion_rows += 1
            # A conversion is only correct if the value AND the unit arrived right: the
            # right number in the wrong unit is not a converted value.
            value_correct = _values_agree(mapping.value, row.expected_value) and (
                (mapping.unit or "").strip().casefold()
                == row.expected_unit.strip().casefold()
            )
            conversion_correct += int(value_correct)

        outcomes.append(
            FieldOutcome(
                gold_id=row.gold_id,
                expected_field=row.expected_field,
                produced_field=mapping.target_field,
                field_correct=correct_field,
                expected_value=row.expected_value,
                produced_value=mapping.value,
                value_correct=value_correct,
                conversion_was_expected=row.needs_conversion,
                candidates=len(candidates),
            )
        )

    return Score(
        confirmed=len(confirmed),
        mapping_accuracy=round(field_correct / len(confirmed), 4),
        conversion_correctness=(
            round(conversion_correct / conversion_rows, 4) if conversion_rows else 1.0
        ),
        conversion_rows=conversion_rows,
        matched=matched,
        unmatched=len(confirmed) - matched,
        ambiguous=ambiguous,
        outcomes=outcomes,
    )
