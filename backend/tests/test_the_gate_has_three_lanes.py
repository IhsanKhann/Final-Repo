"""Law V: three states, never two. auto / review / missing.

A boolean forces the interesting middle case into one of the two wrong bins -- a guess
presented as a fact, or a silent drop. The problem statement asks for neither; it asks for
the field to be flagged for a human. So these tests pin the boundaries, and they pin the
two asymmetric cases that are easy to get backwards and expensive to get wrong on stage.
"""

from __future__ import annotations

import pytest

from backend.engine.gate import (
    DEFAULT_AUTO_THRESHOLD,
    DEFAULT_REVIEW_THRESHOLD,
    GateInput,
    decide,
)


def _at(confidence: float, **overrides) -> GateInput:
    kwargs = dict(confidence=confidence, has_value=True, has_provenance=True)
    kwargs.update(overrides)
    return GateInput(**kwargs)


def test_the_stated_defaults_are_the_agreed_numbers():
    assert (DEFAULT_AUTO_THRESHOLD, DEFAULT_REVIEW_THRESHOLD) == (0.90, 0.60)


def test_the_thresholds_do_not_claim_to_be_calibrated():
    """The sample review flag is uncorrelated with confidence, so it calibrated nothing.

    This flag is the difference between a measured claim and a story, and it defaults to
    the honest value so that forgetting to set it understates rather than overstates.
    """
    assert decide(_at(0.95)).thresholds_are_calibrated is False


@pytest.mark.parametrize(
    "confidence,expected",
    [
        (1.00, "auto"),
        (0.91, "auto"),
        (0.90, "auto"),  # the boundary is inclusive
        (0.8999, "review"),
        (0.75, "review"),
        (0.60, "review"),  # inclusive here too
        (0.5999, "missing"),
        (0.00, "missing"),
    ],
)
def test_confidence_lands_in_exactly_one_of_three_lanes(confidence, expected):
    assert decide(_at(confidence)).status == expected


def test_all_three_lanes_are_reachable():
    """Guards against a refactor that collapses the middle lane into a boolean."""
    statuses = {decide(_at(c)).status for c in (0.95, 0.75, 0.10)}
    assert statuses == {"auto", "review", "missing"}


def test_a_field_with_no_value_is_missing_not_review():
    assert decide(_at(0.99, has_value=False)).status == "missing"


def test_a_value_without_provenance_can_never_be_auto_accepted():
    """However confident. Clicking a cell has to show a page, or the claim is empty."""
    assert decide(_at(0.99, has_provenance=False)).status == "review"


def test_intelligence_being_unavailable_reaches_a_human_rather_than_vanishing():
    """The asymmetry that matters, and the one easiest to get backwards.

    Unavailable means the review tray and never a guess (CLAUDE.md 4). The field is real;
    only our ability to map it was missing. Routing this to `missing` would silently
    convert every provider outage into deleted data, and the stage answer to "what happens
    when the model is down?" would stop being true.
    """
    decision = decide(_at(0.0, has_value=False, forced_review=("intelligence-unavailable",)))
    assert decision.status == "review"


def test_a_model_inventing_a_field_is_refused_rather_than_reviewed():
    """The other half of the asymmetry: there is nothing here for a reviewer to accept."""
    decision = decide(_at(0.99, forced_review=("out-of-declared-fields",)))
    assert decision.status == "missing"


@pytest.mark.parametrize(
    "forced",
    ["magnitude-suspect", "no-conversion-rule", "validation-failed", "ambiguity-declared-by-pack"],
)
def test_a_forced_condition_overrides_a_confident_score(forced):
    assert decide(_at(0.99, forced_review=(forced,))).status == "review"


def test_a_verifier_rejection_drops_the_field_rather_than_downgrading_it():
    """There is no such thing here as a low-confidence claim that survived verification."""
    assert decide(_at(0.99, verifier_rejected=True)).status == "missing"


def test_every_decision_explains_itself_in_words_a_human_reads():
    for confidence in (0.95, 0.75, 0.10):
        reason = decide(_at(confidence)).reason
        assert reason and not reason.startswith("None")
        assert any(ch.isdigit() for ch in reason), "a reason should cite the number it used"


def test_inverted_thresholds_are_refused_rather_than_silently_emptying_the_middle_lane():
    with pytest.raises(ValueError, match="Law V"):
        decide(_at(0.8), auto_threshold=0.5, review_threshold=0.9)
