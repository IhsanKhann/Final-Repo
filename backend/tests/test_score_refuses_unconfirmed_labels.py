"""The scorer's refusal is the feature, so it is tested like one.

The failure this prevents: a confident accuracy number computed against labels no human
confirmed, quoted on stage as a measurement. These tests pin the refusal, the denominator
(confirmed rows, not matched rows), and the rule that a conversion needs the right unit as
well as the right number.
"""

from __future__ import annotations

import pytest

from backend.engine.contracts import Mapping, SourceLocationSheet
from backend.eval.score import (
    MINIMUM_CONFIRMED_ROWS,
    GoldenRow,
    Score,
    Unscoreable,
    confirmed_rows,
    load_golden_set,
    score,
)


def _row(gold_id: str, *, confirmed: bool, conversion: str = "none", **overrides) -> GoldenRow:
    data = dict(
        gold_id=gold_id,
        institution_name="an institution",
        document_file=f"{gold_id.lower()}.pdf",
        document_format="pdf_text",
        product_type="a product",
        source_label="a label",
        value_as_printed="1.0",
        expected_field="f_annual",
        expected_value="1.0",
        expected_unit="u_year",
        conversion_expected=conversion,
        difficulty="the easy case",
        confirmed_by="IK/TK" if confirmed else "",
    )
    data.update(overrides)
    return GoldenRow(**data)


def _mapping(row: GoldenRow, *, field: str | None = None, value: str | None = None,
             unit: str | None = None) -> Mapping:
    return Mapping(
        id=f"m-{row.gold_id}",
        document_id=row.document_file,
        source_label=row.source_label,
        target_field=field if field is not None else row.expected_field,
        raw_value=row.value_as_printed,
        value=value if value is not None else row.expected_value,
        unit=unit if unit is not None else row.expected_unit,
        confidence=0.95,
        status="auto",
        source_location=SourceLocationSheet(sheet="S", cell="A1"),
    )


def test_the_shipped_golden_set_is_not_scoreable_yet():
    """Guards the live state: every expected_field is PROPOSED until a human confirms it."""
    rows = load_golden_set()
    assert len(rows) == 30, "the golden set should hold 30 rows"
    result = score([], rows)
    assert isinstance(result, Unscoreable)
    assert result.confirmed == len(confirmed_rows(rows))


def test_an_unconfirmed_golden_set_produces_no_number_at_all():
    rows = [_row(f"G{i:03d}", confirmed=False) for i in range(30)]
    result = score([_mapping(r) for r in rows], rows)
    assert isinstance(result, Unscoreable)
    assert not hasattr(result, "mapping_accuracy")


def test_the_refusal_names_how_many_rows_are_confirmed():
    """A refusal that does not say what is missing gets worked around rather than fixed."""
    rows = [_row(f"G{i:03d}", confirmed=i < 7) for i in range(30)]
    result = score([], rows)
    assert isinstance(result, Unscoreable)
    assert result.confirmed == 7
    assert result.required == MINIMUM_CONFIRMED_ROWS
    assert "7 of 30" in result.reason
    assert "30 are required" in result.reason


def test_one_row_short_still_refuses():
    """Off-by-one here would be the difference between a measurement and a story."""
    rows = [_row(f"G{i:03d}", confirmed=i < 29) for i in range(30)]
    assert isinstance(score([], rows), Unscoreable)


def test_a_fully_confirmed_golden_set_is_scored():
    rows = [_row(f"G{i:03d}", confirmed=True) for i in range(30)]
    result = score([_mapping(r) for r in rows], rows)
    assert isinstance(result, Score)
    assert result.mapping_accuracy == 1.0
    assert result.confirmed == 30
    assert result.complete is True


def test_a_row_the_pipeline_never_produced_counts_as_wrong_not_as_absent():
    """The denominator is confirmed rows. Otherwise accuracy rises as coverage falls."""
    rows = [_row(f"G{i:03d}", confirmed=True) for i in range(30)]
    produced = [_mapping(r) for r in rows[:15]]  # half the rows never mapped
    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.matched == 15
    assert result.unmatched == 15
    assert result.mapping_accuracy == 0.5, "an unmapped row must not be excluded from the denominator"
    assert result.complete is False


def test_mapping_onto_the_wrong_field_is_counted_wrong():
    rows = [_row(f"G{i:03d}", confirmed=True) for i in range(30)]
    produced = [_mapping(r, field="f_something_else" if i < 6 else None) for i, r in enumerate(rows)]
    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.mapping_accuracy == 0.8


def test_a_conversion_needs_the_right_number_and_the_right_unit():
    """The right number in the wrong unit is not a converted value."""
    rows = [
        _row("G001", confirmed=True, conversion="x12", expected_value="4.0596"),
        _row("G002", confirmed=True, conversion="x12", expected_value="4.0596"),
    ] + [_row(f"G{i:03d}", confirmed=True) for i in range(3, 31)]

    produced = [
        _mapping(rows[0], value="4.0596", unit="u_year"),       # correct
        _mapping(rows[1], value="4.0596", unit="u_month"),      # right number, wrong unit
    ] + [_mapping(r) for r in rows[2:]]

    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.conversion_rows == 2
    assert result.conversion_correctness == 0.5


def test_conversion_correctness_is_not_penalised_when_nothing_needed_converting():
    rows = [_row(f"G{i:03d}", confirmed=True) for i in range(30)]
    result = score([_mapping(r) for r in rows], rows)
    assert isinstance(result, Score)
    assert result.conversion_rows == 0
    assert result.conversion_correctness == 1.0


def test_the_monthly_round_trip_is_scored_correct_within_its_printing_bound():
    """The x12 case cannot round-trip exactly, and the scorer must not punish that.

    The generator prints the monthly quote to four decimals because that is what a rate
    sheet prints, so recovering the annual figure multiplies a rounded number and the
    error is bounded by 12 x 0.00005 = 0.0006 percentage points. A tolerance tighter than
    that fails every monthly row while the converter is working perfectly -- and the
    obvious fix for a red conversion test is to loosen it until it passes and stop looking.
    """
    rows = [_row("G001", confirmed=True, conversion="x12", expected_value="4.0596")] + [
        _row(f"G{i:03d}", confirmed=True) for i in range(2, 31)
    ]
    # 0.2240 printed, x12 -> 2.688 against a true 4.0596-style figure would be wrong; the
    # realistic case is a recovery that differs only in the last printed place.
    produced = [_mapping(rows[0], value="4.0602", unit="u_year")] + [
        _mapping(r) for r in rows[1:]
    ]
    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.conversion_correctness == 1.0, (
        "a recovery within the printing bound was scored wrong, which would make the "
        "conversion criterion unpassable by construction"
    )


def test_a_recovery_outside_the_printing_bound_is_still_scored_wrong():
    """The tolerance must not be so loose that a genuine conversion error passes."""
    rows = [_row("G001", confirmed=True, conversion="x12", expected_value="4.0596")] + [
        _row(f"G{i:03d}", confirmed=True) for i in range(2, 31)
    ]
    produced = [_mapping(rows[0], value="4.12", unit="u_year")] + [
        _mapping(r) for r in rows[1:]
    ]
    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.conversion_correctness == 0.0


@pytest.mark.parametrize(
    "printed", ["2026-07-01", "07/01/2026", "01 Jul 2026", "July 1, 2026"]
)
def test_the_same_day_printed_in_four_house_styles_is_one_value(printed):
    """Each institution prints dates its own way. That is the problem, not a mismatch."""
    rows = [
        _row(
            "G001",
            confirmed=True,
            expected_field="effective_date",
            expected_value="2026-07-01",
            expected_unit="",
        )
    ] + [_row(f"G{i:03d}", confirmed=True) for i in range(2, 31)]
    produced = [_mapping(rows[0], value=printed, unit="")] + [_mapping(r) for r in rows[1:]]
    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.mapping_accuracy == 1.0
    assert result.outcomes[0].field_correct is True


def test_money_printed_with_a_currency_sign_is_the_same_value():
    rows = [
        _row("G001", confirmed=True, conversion="usd", expected_value="500", expected_unit="usd")
    ] + [_row(f"G{i:03d}", confirmed=True) for i in range(2, 31)]
    produced = [_mapping(rows[0], value="$500", unit="usd")] + [
        _mapping(r) for r in rows[1:]
    ]
    result = score(produced, rows)
    assert isinstance(result, Score)
    assert result.conversion_correctness == 1.0


def test_a_golden_row_with_an_unexpected_column_is_refused_rather_than_ignored():
    with pytest.raises(Exception):
        GoldenRow(
            gold_id="G001", institution_name="x", document_file="x.pdf", document_format="pdf_text",
            product_type="p", source_label="l", value_as_printed="1", expected_field="f",
            expected_value="1", expected_unit="u", conversion_expected="none",
            difficulty="d", confirmed_by="", a_column_nobody_declared="surprise",
        )
