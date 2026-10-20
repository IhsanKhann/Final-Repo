"""The three-lane gate. Law V lives here: auto / review / missing, never a boolean.

Exists because the interesting case is always the middle one. A boolean forces an
ambiguous field into one of the two wrong bins -- either a guess presented as a fact, or a
silent drop -- and the problem statement asks for neither. It asks for the field to be
flagged for a human.

On the two thresholds, stated honestly because the alternative is a false claim on stage:
0.90 and 0.60 are STATED DEFAULTS, not calibrated values. They cannot be calibrated
against the sample data's own review flag, because that flag is uncorrelated with the
confidence score it would have to correlate with -- flagged rows span 0.61-0.99 and
unflagged rows span 0.60-0.99, which is the same range. Fitting against those labels would
be fitting against noise. They are fitted against the hand-labelled golden set instead, and
until that fitting is run and recorded they remain defaults and we say so.

What this module refuses to do:
  * It refuses to drop a field. A value we will not claim becomes `missing`, which is
    written and shown. Silence is the one outcome the statement rules out.
  * It refuses to auto-accept anything without provenance, whatever its confidence.
  * It refuses to read config. Thresholds arrive as arguments so the decision is a pure
    function of its inputs and a test can pin it without a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.engine.contracts import MappingStatus

#: Stated defaults. See the module docstring before quoting these as calibrated.
DEFAULT_AUTO_THRESHOLD = 0.90
DEFAULT_REVIEW_THRESHOLD = 0.60

ForcedReview = Literal[
    "magnitude-suspect",
    "no-conversion-rule",
    "validation-failed",
    "intelligence-unavailable",
    "out-of-declared-fields",
    "ambiguity-declared-by-pack",
]

#: Forced conditions that mean "we will not claim a value here", as opposed to "a human
#: must look at this". The distinction matters and is not symmetric: a model naming a field
#: the pack never declared is a refusal -- there is nothing for a reviewer to accept -- but
#: intelligence being unavailable is explicitly a review-tray outcome (CLAUDE.md 4), since
#: the field is perfectly real and only our ability to map it was missing.
FORCED_TO_MISSING: frozenset[str] = frozenset({"out-of-declared-fields"})


class GateInput(BaseModel):
    """Everything the lane decision is allowed to depend on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confidence: float = Field(ge=0.0, le=1.0)
    has_value: bool
    has_provenance: bool
    #: Conditions that send a field to review however confident it looked.
    forced_review: tuple[ForcedReview, ...] = ()
    #: A verifier rejection. The field is dropped, not downgraded: there is no such thing
    #: here as a low-confidence claim that survives verification.
    verifier_rejected: bool = False
    #: True when the value came from a model choosing among candidates the pack declares.
    #: Such a proposal never drops below `review`, however low its confidence -- see the
    #: reasoning at the branch in `decide`.
    constrained_proposal: bool = False


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: MappingStatus
    reason: str
    auto_threshold: float
    review_threshold: float
    thresholds_are_calibrated: bool = False


def decide(
    gate_input: GateInput,
    *,
    auto_threshold: float = DEFAULT_AUTO_THRESHOLD,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    thresholds_are_calibrated: bool = False,
) -> GateDecision:
    """Put one field in exactly one of three lanes, and say why in words a human reads."""
    if review_threshold > auto_threshold:
        raise ValueError(
            f"review threshold {review_threshold} above auto threshold {auto_threshold}: "
            "the middle lane would be empty and Law V would be a boolean in disguise"
        )

    def made(status: MappingStatus, reason: str) -> GateDecision:
        return GateDecision(
            status=status,
            reason=reason,
            auto_threshold=auto_threshold,
            review_threshold=review_threshold,
            thresholds_are_calibrated=thresholds_are_calibrated,
        )

    if gate_input.verifier_rejected:
        return made("missing", "the verifier did not find this value supported by its source")

    # Forced conditions are read before has_value, because the most important one --
    # intelligence being unavailable -- has no value by definition and must still reach a
    # human. Ordering this after the has_value check would silently convert every provider
    # outage into a dropped field, which is the exact failure the three lanes exist to stop.
    refusals = [r for r in gate_input.forced_review if r in FORCED_TO_MISSING]
    if refusals:
        return made("missing", f"no value is claimed: {', '.join(refusals)}")

    if gate_input.forced_review:
        listed = ", ".join(gate_input.forced_review)
        return made("review", f"sent to review regardless of confidence: {listed}")

    if not gate_input.has_value:
        return made("missing", "no value for this field was found in the document")

    if not gate_input.has_provenance:
        return made("review", "no source location, so this value cannot be auto-accepted")

    if gate_input.confidence >= auto_threshold:
        return made("auto", f"confidence {gate_input.confidence:.2f} at or above {auto_threshold:.2f}")

    if gate_input.confidence >= review_threshold:
        return made(
            "review",
            f"confidence {gate_input.confidence:.2f} between {review_threshold:.2f} "
            f"and {auto_threshold:.2f}",
        )

    # Below the floor, but a model choosing from the pack's own declared fields still goes
    # to a human rather than being discarded. Measured case: a real model mapped an
    # undeclared label onto the right field at confidence 0.40 and said honestly that it
    # was reasoning by concept rather than by match. Filed as `missing`, that correct
    # answer was never shown, the analyst re-did it from scratch, and no precedent was
    # written -- so the feedback loop learned nothing from exactly the case it exists for.
    #
    # The floor is not protecting us here: retrieval constrains the choice to declared
    # fields, so the model cannot invent one. What the floor is for is a value we would
    # otherwise CLAIM, and a review-lane row claims nothing -- it asks.
    if gate_input.constrained_proposal:
        return made(
            "review",
            f"confidence {gate_input.confidence:.2f} is below {review_threshold:.2f}, but "
            "this names a field the pack declares, so it is offered to a reviewer rather "
            "than discarded",
        )

    return made(
        "missing",
        f"confidence {gate_input.confidence:.2f} below {review_threshold:.2f}, so no value "
        "is claimed for this field",
    )
