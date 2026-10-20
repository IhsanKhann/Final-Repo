"""Unit conversion driven entirely by factors the customer declared in their pack.

Exists because "unit conversion correctness" is a scored criterion, and a lookup table
wins it 100% while a model wins it 97% inexplicably. So there is no model here and there
never will be: edit a factor in the pack YAML, re-run, and the column changes.

What this module refuses to do:
  * It refuses to know what any unit means. Units are opaque strings that arrive from the
    pack. There is no table of real-world units in this file and there must not be, or
    meaning would live in the engine instead of in the customer's rulebook (Law II).
  * It refuses to guess a conversion it was not given. An unknown unit pair is reported,
    not approximated via some intermediate the customer never declared.
  * It refuses to convert in binary floating point. Decimal, because a demo that shows
    1.3599999999999999 has lost the argument before anyone reads the number.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.engine.contracts import Conversion

#: A conversion that moves a value by more than this many orders of magnitude is suspect
#: regardless of how confident anything was. Three is deliberately generous: unit families
#: a customer actually declares rarely span more, and a factor typo usually overshoots it.
MAGNITUDE_ORDERS_LIMIT = 3

#: Characters stripped from a raw value before parsing. Symbols, not domain nouns: a
#: currency sign or a percent sign is punctuation here, carrying no meaning this layer
#: is allowed to interpret.
_STRIP = re.compile(r"[,\s%$£€ ]")
_TRAILING_UNIT = re.compile(r"[^0-9eE+\-.].*$")


class ConversionRule(BaseModel):
    """One declared conversion. The pack owns these; this module only applies them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    from_unit: str
    to_unit: str
    factor: Decimal
    #: Human-readable, for the UI. The pack author writes it, so it says what they meant.
    formula_text: str


class ConversionOutcome(BaseModel):
    """What happened, including when nothing happened. Never raises across the seam."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["converted", "identity", "no-rule", "unparseable"]
    value: str | None = None
    unit: str | None = None
    conversion: Conversion | None = None
    #: Set when the conversion moved the value further than MAGNITUDE_ORDERS_LIMIT.
    #: The gate turns this into a review lane regardless of confidence.
    magnitude_suspect: bool = False
    detail: str | None = None


class RuleTable(BaseModel):
    """Lookup over declared rules, keyed by (from_unit, to_unit), case-folded."""

    model_config = ConfigDict(extra="forbid")

    rules: dict[tuple[str, str], ConversionRule] = Field(default_factory=dict)

    @classmethod
    def from_rules(cls, rules: list[ConversionRule]) -> RuleTable:
        return cls(rules={(r.from_unit.casefold(), r.to_unit.casefold()): r for r in rules})

    def find(self, from_unit: str, to_unit: str) -> ConversionRule | None:
        return self.rules.get((from_unit.casefold(), to_unit.casefold()))


def parse_numeric(raw: str) -> Decimal | None:
    """Pull a number out of a value as a document reported it, or return None.

    Returns None rather than raising: an unparseable value is a review-lane fact about the
    document, not an exception for a caller to handle.
    """
    if raw is None:
        return None
    text = _STRIP.sub("", str(raw)).strip()
    if not text:
        return None
    text = _TRAILING_UNIT.sub("", text)
    if text in {"", "-", "+", ".", "-.", "+."}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _format(value: Decimal) -> str:
    """Render a Decimal the same way every time, because the export is a render (Law IV)."""
    normalized = value.normalize()
    sign, digits, exponent = normalized.as_tuple()
    # Avoid scientific notation, which would make the same number render two ways.
    if isinstance(exponent, int) and exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _orders_of_magnitude(factor: Decimal) -> int:
    if factor == 0:
        return MAGNITUDE_ORDERS_LIMIT + 1
    magnitude = abs(factor.copy_abs().log10())
    return int(magnitude.to_integral_value(rounding="ROUND_FLOOR"))


def convert(
    raw_value: str,
    raw_unit: str | None,
    target_unit: str | None,
    table: RuleTable,
) -> ConversionOutcome:
    """Apply a declared conversion, or say clearly why none was applied.

    Pure. Same arguments in, same outcome out, with no reference to anything outside the
    rule table it was handed.
    """
    number = parse_numeric(raw_value)
    if number is None:
        return ConversionOutcome(
            outcome="unparseable", detail=f"no number could be read from {raw_value!r}"
        )

    # Nothing to do: no target declared, or the document already reports the target unit.
    if not target_unit or not raw_unit or raw_unit.casefold() == target_unit.casefold():
        return ConversionOutcome(
            outcome="identity", value=_format(number), unit=target_unit or raw_unit
        )

    rule = table.find(raw_unit, target_unit)
    if rule is None:
        return ConversionOutcome(
            outcome="no-rule",
            value=_format(number),
            unit=raw_unit,
            detail=(
                f"the pack declares no conversion from {raw_unit!r} to {target_unit!r}; "
                "this layer will not invent one"
            ),
        )

    with localcontext() as ctx:
        ctx.prec = 28
        converted = number * rule.factor

    return ConversionOutcome(
        outcome="converted",
        value=_format(converted),
        unit=rule.to_unit,
        conversion=Conversion(
            factor=float(rule.factor),
            rule_id=rule.id,
            formula_text=rule.formula_text,
        ),
        magnitude_suspect=_orders_of_magnitude(rule.factor) > MAGNITUDE_ORDERS_LIMIT,
    )
