"""Round reports, and the comparability check that keeps them honest.

Exists because "improvement rate from the feedback loop" is a scored criterion, and a
number that improved because the inputs moved is worse than no number at all -- it is a
false claim made with a chart. So comparability is part of the report, not a nicety: if any
of the five controlled variables differs between two rounds, the report says NOT COMPARABLE
and the UI shows that instead of a delta.

The five controlled variables, from README section 10:
    documents, pack version, model, temperature, prompt version.

What this module refuses to do:
  * It refuses to compute a delta across rounds that are not comparable.
  * It refuses to call a model (Law I).
  * It refuses to estimate effort saved from anything but the pipeline's own counters.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Sequence

from backend.engine.contracts import Mapping, RoundReport

#: The five variables that must not move between rounds, by RoundReport field name.
CONTROLLED_VARIABLES: tuple[str, ...] = (
    "documents_fingerprint",
    "pack_version",
    "model",
    "temperature",
    "prompt_version",
)

#: Metrics a delta is computed for when two rounds are comparable.
DELTA_METRICS: tuple[str, ...] = (
    "mapping_accuracy",
    "conversion_correctness",
    "auto_accepted",
    "flagged",
    "missing",
    "precedents_applied",
    "model_calls_skipped",
    "analyst_minutes_saved",
    "cost_usd",
)


def fingerprint_documents(document_hashes: Iterable[str]) -> str:
    """A stable identity for "the same documents", order-independent.

    Sorted before hashing so that re-running the same set in a different order does not
    read as a different corpus -- which would void a comparison that was in fact valid.
    """
    joined = "|".join(sorted(document_hashes))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def count_lanes(mappings: Sequence[Mapping]) -> tuple[int, int, int]:
    """(auto_accepted, flagged, missing). `approved` counts as auto: a human signed it."""
    auto = sum(1 for m in mappings if m.status in ("auto", "approved"))
    flagged = sum(1 for m in mappings if m.status == "review")
    missing = sum(1 for m in mappings if m.status in ("missing", "rejected"))
    return auto, flagged, missing


def analyst_minutes_saved(auto_accepted: int, minutes_per_field: float) -> float:
    """Measured from the pipeline's own counter, not estimated from a benchmark.

    Only auto-accepted fields count. A field that went to review did not save the analyst
    anything -- they still looked at it.
    """
    return round(auto_accepted * minutes_per_field, 2)


def compare(current: RoundReport, previous: RoundReport | None) -> RoundReport:
    """Attach a delta, or mark the pair not comparable and say which variable moved."""
    if previous is None:
        return current.model_copy(update={"comparable": True, "delta_vs_previous": None})

    moved = [
        name
        for name in CONTROLLED_VARIABLES
        if getattr(current, name) != getattr(previous, name)
    ]
    if moved:
        return current.model_copy(
            update={
                "comparable": False,
                "not_comparable_reason": (
                    "these controlled variables changed between rounds "
                    f"{previous.round} and {current.round}: {', '.join(moved)}. "
                    "The improvement cannot be attributed to the feedback loop."
                ),
                "delta_vs_previous": None,
            }
        )

    delta = {
        metric: round(float(getattr(current, metric)) - float(getattr(previous, metric)), 4)
        for metric in DELTA_METRICS
    }
    return current.model_copy(
        update={"comparable": True, "not_comparable_reason": None, "delta_vs_previous": delta}
    )
