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
  * Matching a mapping to a golden row needs more than (document, source_label) whenever
    one document reports the same label on several product rows -- a rate sheet does. Until
    the adapters qualify `source_label` per row, `match_key` is injectable and `unmatched`
    is reported rather than hidden. See the note on MatchKey.

What this module refuses to do: call a model, and report a number it cannot stand behind.
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
    source_file: str
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
MatchKey = Callable[[GoldenRow], tuple[str, ...]]
MappingKey = Callable[[Mapping], tuple[str, ...]]


def default_match_key(row: GoldenRow) -> tuple[str, ...]:
    return (row.source_file.casefold(), row.source_label.casefold())


def default_mapping_key(mapping: Mapping) -> tuple[str, ...]:
    return (mapping.document_id.casefold(), mapping.source_label.casefold())


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
    """Compare as numbers if both are numbers, as dates if both are dates, else as text.

    Never as raw strings first: the fixtures deliberately print the same quantity in each
    institution's own house style, which is the problem the product solves. Scoring that
    as a mismatch would mark the pipeline wrong for being right.
    """
    if produced is None:
        return False

    left = parse_numeric(produced)
    right = parse_numeric(expected)
    if left is not None and right is not None:
        return abs(left - right) <= VALUE_TOLERANCE

    left_date = _as_date(produced)
    right_date = _as_date(expected)
    if left_date is not None and right_date is not None:
        return left_date == right_date

    return produced.strip().casefold() == expected.strip().casefold()


def score(
    mappings: Sequence[Mapping],
    rows: Sequence[GoldenRow] | None = None,
    *,
    minimum_confirmed: int = MINIMUM_CONFIRMED_ROWS,
    match_key: MatchKey = default_match_key,
    mapping_key: MappingKey = default_mapping_key,
) -> Score | Unscoreable:
    """Measure a run, or refuse and say exactly how short of confirmed labels we are."""
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

    produced: dict[tuple[str, ...], Mapping] = {}
    for mapping in mappings:
        produced.setdefault(mapping_key(mapping), mapping)

    outcomes: list[FieldOutcome] = []
    field_correct = 0
    conversion_rows = 0
    conversion_correct = 0
    matched = 0

    for row in confirmed:
        mapping = produced.get(match_key(row))
        if mapping is None:
            outcomes.append(
                FieldOutcome(
                    gold_id=row.gold_id,
                    expected_field=row.expected_field,
                    produced_field=None,
                    field_correct=False,
                    expected_value=row.expected_value,
                    produced_value=None,
                    conversion_was_expected=row.needs_conversion,
                    note="the pipeline produced no mapping for this row, which counts as wrong",
                )
            )
            if row.needs_conversion:
                conversion_rows += 1
            continue

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
        outcomes=outcomes,
    )
