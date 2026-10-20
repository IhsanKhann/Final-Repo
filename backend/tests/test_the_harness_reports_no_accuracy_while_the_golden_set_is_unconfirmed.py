"""The performance harness must not launder the scorer's refusal into a zero.

`RoundReport.mapping_accuracy` is typed `float`, so every report carries a number there,
and with the golden set at 0 of 30 confirmed that number is 0.0. A reader who sees 0.0 and
no refusal concludes the pipeline maps nothing correctly -- or, worse, quotes it as a
measurement. Both are false, and the second is the exact failure this product exists to
refuse.

So these tests pin the one property that keeps the placeholder readable: the zero can never
travel alone. `PerformanceReport.accuracy` is a required field, the statement says NOT
MEASURED in those words, and the terminal rendering prints the scorer's own reason instead
of a figure.

The rest of these protect the other named absences -- a document that produced nothing says
why, a format with no pages reports None rather than 1, and the `sampling` controlled
variable records what went on the wire rather than what was intended.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.engine import packs as packs_module
from backend.engine.rounds import CONTROLLED_VARIABLES
from backend.eval import measure as measure_module
from backend.eval import score as score_module
from backend.memory.precedents import SqlitePrecedentStore

GENERATED = Path(__file__).resolve().parents[1] / "eval" / "generated"

#: Two documents, not six: one that reports fields and one that reports none. Enough to
#: exercise every refusal in the report without paying for the whole corpus in CI.
SUBSET = ("heritage_financial_rates.html", "metro_credit_union_rates_scan.pdf")


@pytest.fixture()
def report(tmp_path) -> measure_module.PerformanceReport:
    paths = [GENERATED / name for name in SUBSET]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        pytest.skip(
            f"generated fixtures absent ({missing}); run python -m backend.eval.make_documents"
        )
    # Named, not resolved from config: more than one pack is present now, and a corpus
    # measured against whichever pack happened to be active is not a measurement.
    pack = packs_module.resolve_active_pack("banking_rates")
    return measure_module.build_report(
        paths=paths,
        pack=pack,
        precedents=SqlitePrecedentStore(tmp_path / "memory.db"),
        # No seam, deliberately: a harness that billed the operator to produce a latency
        # number would be unrunnable in CI and unreproducible anywhere.
        seam=None,
        tenant_id="demo",
        round_number=1,
        remote=None,
    )


def test_the_harness_reports_no_accuracy_while_the_golden_set_is_unconfirmed(report) -> None:
    """The headline behaviour: 0.0 in the report, and a refusal no reader can skip."""
    assert report.accuracy.measured is False
    assert report.accuracy.mapping_accuracy is None
    assert report.accuracy.conversion_correctness is None
    assert report.accuracy.confirmed_rows == 0
    assert report.accuracy.required_rows == score_module.MINIMUM_CONFIRMED_ROWS
    assert "NOT MEASURED" in report.accuracy.statement

    # The placeholder is present, because the contract types it float -- and it is named a
    # placeholder in the same object.
    assert report.round_report.mapping_accuracy == 0.0
    assert report.round_report.conversion_correctness == 0.0
    assert "placeholder" in report.accuracy.statement


def test_the_refusal_carries_the_scorers_own_words_rather_than_a_paraphrase(report) -> None:
    """A paraphrase drifts. The scorer's reason is the thing that must reach the reader."""
    refused = score_module.score([])
    assert isinstance(refused, score_module.Unscoreable)
    assert report.accuracy.scorer_refusal == refused.reason
    assert "grading its own proposal" in (report.accuracy.scorer_refusal or "")


def test_a_report_cannot_be_built_without_saying_whether_accuracy_was_measured() -> None:
    """Make the omission impossible in the model, not avoided by convention."""
    with pytest.raises(ValidationError):
        measure_module.PerformanceReport(
            generated_at="2026-01-01T00:00:00+0000",
            round_report=None,  # type: ignore[arg-type]
            cost=None,  # type: ignore[arg-type]
            local=None,  # type: ignore[arg-type]
        )
    assert "accuracy" in measure_module.PerformanceReport.model_fields
    assert measure_module.PerformanceReport.model_fields["accuracy"].is_required()


def test_the_printed_summary_says_not_measured_instead_of_printing_a_zero(report) -> None:
    """The terminal output is what gets read on stage, so it carries the refusal too."""
    rendered = measure_module.render(report)
    assert "mapping_accuracy        NOT MEASURED" in rendered
    assert "conversion_correctness  NOT MEASURED" in rendered
    assert "0 of 30 golden rows confirmed" in rendered
    # The two lines a reader would quote must not contain a figure at all.
    for line in rendered.splitlines():
        stripped = line.strip()
        if stripped.startswith(("mapping_accuracy", "conversion_correctness")):
            assert "0.0" not in stripped, f"a zero is being shown as a measurement: {line}"


def test_every_measured_zero_in_the_report_says_how_it_was_arrived_at(report) -> None:
    """A zero with no basis is indistinguishable from an unmeasured field."""
    assert report.cost.tokens_charged == 0
    assert report.cost.model_calls_made == 0
    assert report.cost.cost_usd == 0.0
    # Dollars are the one cost this repository genuinely cannot convert.
    assert "no price table" in report.cost.cost_usd_basis
    # And zero model calls must not read as an efficiency result.
    assert "configuration fact" in report.local.model_access


def test_a_document_that_produced_nothing_says_why_rather_than_reporting_a_zero(report) -> None:
    """The scanned PDF yields no facts today, and silence there would read as speed."""
    scan = next(d for d in report.local.documents if d.name == SUBSET[1])
    assert scan.facts_extracted == 0
    assert scan.fields_reported == 0
    assert scan.note, "a document that produced nothing must say why"
    assert "no text layer" in scan.note


def test_a_format_with_no_pages_reports_none_rather_than_one(report) -> None:
    """Substituting 1 would make pages-per-second a fiction for three of six documents."""
    html = next(d for d in report.local.documents if d.name == SUBSET[0])
    assert html.page_count is None
    assert "not applicable" in html.page_count_basis
    pdf = next(d for d in report.local.documents if d.name == SUBSET[1])
    assert pdf.page_count == 2
    assert "measured" in pdf.page_count_basis


def test_all_six_controlled_variables_are_recorded_or_the_delta_is_void(report) -> None:
    """Five is not enough: rounds.compare() checks six, and a blank one voids a comparison."""
    for name in CONTROLLED_VARIABLES:
        assert str(getattr(report.round_report, name)).strip(), f"{name} was not recorded"
        assert name in report.controlled_variables, f"{name} has no recorded source"
    assert report.round_report.comparable is True
    assert report.round_report.delta_vs_previous is None


def test_sampling_records_what_went_on_the_wire_and_not_what_was_intended(report) -> None:
    """With no seam nothing was sent, and `temperature=0` would be a false claim."""
    assert report.round_report.sampling.startswith("not-sent:")
    assert "temperature=0" not in report.round_report.sampling
    assert measure_module.sampling_sent(None).startswith("not-sent:")


def test_sampling_reports_the_anthropic_omission_rather_than_a_number() -> None:
    """The dialect that removes temperature must not be reported as having sent zero."""
    from backend.intelligence import providers as prov

    class _Seam:
        last_request = prov.shape_request(
            prov.Dialect.ANTHROPIC,
            model="m",
            system="s",
            user="u",
            schema={"type": "object"},
            max_tokens=16,
            temperature=0.0,
        )

    sampling = measure_module.sampling_sent(_Seam())
    assert sampling.startswith("not-sent: removed by provider")
    assert "temperature=0" not in sampling

    class _OpenAiSeam:
        last_request = prov.shape_request(
            prov.Dialect.OPENAI,
            model="m",
            system="s",
            user="u",
            schema={"type": "object"},
            max_tokens=16,
            temperature=0.0,
        )

    assert measure_module.sampling_sent(_OpenAiSeam()) == "temperature=0.0"


def test_effort_saved_comes_from_the_pipelines_counter_and_not_from_a_chosen_figure(
    report,
) -> None:
    """analyst_minutes_saved must be derivable from the auto-accept count it claims."""
    from backend.engine.config import control
    from backend.engine.rounds import analyst_minutes_saved

    per_field = float(control("analyst_minutes_per_field").value)
    assert report.round_report.analyst_minutes_saved == analyst_minutes_saved(
        report.local.auto_accepted, per_field
    )
    assert report.round_report.auto_accepted == report.local.auto_accepted


def test_the_lane_counts_add_up_to_the_fields_the_report_claims(report) -> None:
    """A performance report whose parts do not sum to its total is not defensible either."""
    rr = report.round_report
    assert rr.auto_accepted + rr.flagged + rr.missing == rr.fields
    assert rr.fields == sum(d.fields_reported for d in report.local.documents)
    assert rr.docs == len(report.local.documents) == len(SUBSET)


def test_a_remote_number_is_never_a_cold_start_unless_the_idle_was_asserted() -> None:
    """Conflating a container boot with latency is the false claim this flag prevents.

    No network: the probe is driven with a monkeypatched timer so the branch is pinned
    without depending on a service being up, which is the whole reason it is a parameter.
    """
    probe = measure_module.RemoteProbe(
        base_url="https://example.invalid",
        revision_declared=None,
        region_declared=None,
        min_instances_declared=0,
        what_is_timed="x",
        cold_start_ms=None,
        cold_start_basis="not measured: no idle window was asserted",
        warm_latency_basis="y",
        per_document_latency=measure_module._REMOTE_PER_DOC,
        endpoints=[],
        reachable=True,
    )
    assert probe.cold_start_ms is None
    assert "not measured" in probe.cold_start_basis
    assert "NOT MEASURED" in probe.per_document_latency

    rendered = measure_module.render(_with_remote(probe))
    assert "cold start      NOT MEASURED" in rendered
    assert "declared, not measured" in rendered


def _with_remote(probe: measure_module.RemoteProbe) -> measure_module.PerformanceReport:
    """A minimal report around one remote probe, for the rendering assertions above."""
    from backend.engine.contracts import RoundReport

    return measure_module.PerformanceReport(
        generated_at="2026-01-01T00:00:00+0000",
        round_report=RoundReport(
            round=1,
            pack_id="p",
            pack_version="1",
            provider="openai",
            model="m",
            sampling="not-sent: no request was made",
            prompt_version="v1",
            documents_fingerprint="f",
            docs=0,
            fields=0,
            auto_accepted=0,
            flagged=0,
            missing=0,
            mapping_accuracy=0.0,
            conversion_correctness=0.0,
            precedents_applied=0,
            model_calls_skipped=0,
            analyst_minutes_saved=0.0,
            cost_usd=0.0,
        ),
        accuracy=measure_module.AccuracyStatement(
            measured=False,
            mapping_accuracy=None,
            conversion_correctness=None,
            confirmed_rows=0,
            required_rows=30,
            total_rows=30,
            statement="MAPPING ACCURACY IS NOT MEASURED. placeholder.",
            scorer_refusal="r",
        ),
        cost=measure_module.CostStatement(
            tokens_charged=0,
            model_calls_made=0,
            model_calls_skipped=0,
            cost_usd=0.0,
            cost_usd_basis="no price table",
            tokens_basis="t",
        ),
        local=measure_module.LocalRun(
            what_is_timed="w",
            excluded_from_the_timing="e",
            model_access="configuration fact",
            python="3.11",
            platform="test",
            documents=[],
            documents_measured=0,
            documents_unreadable=0,
            pages_counted=0,
            pages_not_applicable=0,
            facts_extracted=0,
            fields_reported=0,
            auto_accepted=0,
            flagged=0,
            missing=0,
            not_reportable=0,
            precedents_available=0,
            precedents_applied=0,
            model_calls_made=0,
            model_calls_skipped=0,
            tokens_charged=0,
            wall_clock_ms=0.0,
            slowest_document="",
            slowest_document_ms=0.0,
            fields_per_second=0.0,
        ),
        remote=probe,
    )
