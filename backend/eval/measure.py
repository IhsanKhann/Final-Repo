"""Measures what a run actually costs, and names every cost it cannot measure.

Why it exists: performance was the one property of this system with no number attached to
it. Governance, provenance and the gate all have tests; latency, throughput and cost per
document had nothing, and a deployed health page was rendering a hardcoded fallback
latency, which is worse than a blank -- it is a measurement-shaped lie. So this module runs
the six generated documents through the real pipeline, one document at a time, with a
stopwatch around each stage, and writes a real `RoundReport` with all SIX controlled
variables recorded.

The discipline it exists to enforce is the one about the numbers it does NOT have:

  * **Accuracy.** `eval/score.py` refuses to score below 30 confirmed golden rows and the
    golden set sits at 0. `RoundReport.mapping_accuracy` is typed `float`, so a report must
    carry some number there; this harness puts 0.0 in the report and makes it impossible to
    read that 0.0 without the refusal, because `PerformanceReport.accuracy` is a required
    field and `render()` prints `NOT MEASURED` and the scorer's own reason instead of a
    figure. Mapping accuracy is not measurable today. Latency is. The report says which.
  * **Dollars.** There is no price table in this repository, so a token count cannot be
    turned into a cost. `cost_usd` is 0.0 here because *zero tokens were charged*, which is
    a measurement; the dollars-per-token conversion is named unmeasurable rather than
    guessed at.
  * **Model calls.** By default this harness configures no seam at all, so `model_calls_made`
    is 0. That zero is a configuration fact, not an efficiency result, and the report says
    so in those words -- otherwise "0 model calls" reads as a boast.
  * **Cold start.** The deployed service runs at min-instances 0, so its first request after
    an idle window is a container boot, not latency. Reporting the two together would be a
    false performance claim, so `cold_start_ms` is populated only when the operator passes
    `--remote-idle-seconds`, asserting the instance really had scaled to zero. Otherwise it
    is null with a reason.
  * **Pages.** A spreadsheet, an HTML page and a text file have no page count. The adapters
    return None and this harness keeps the None with a basis string rather than writing 1.

What it refuses to do:
  * It refuses to call a model. It makes no call of its own, and by default it hands the
    pipeline no seam, so the pipeline makes none either. `--allow-model-calls` is an
    explicit opt-in, and the run is labelled when it is used.
  * It refuses to touch the deployed service with anything but GET. An upload there would
    write rows into the demo's database and -- because that revision has a provider key in
    its config store -- would make live billable calls. So remote numbers are HTTP
    round-trip latency on read-only endpoints, labelled as exactly that.
  * It refuses to average a cold start with a warm one, or a local number with a remote one.
  * It refuses to estimate effort saved. `analyst_minutes_saved` comes from
    `rounds.analyst_minutes_saved()` over the pipeline's own auto-accept counter.
  * It refuses to emit a zero that reads as a measurement. Every zero in the artifact has a
    `*_basis` string next to it saying how it was arrived at.

Run it:

    python -m backend.eval.measure --pack banking_rates
    python -m backend.eval.measure --pack banking_rates --remote https://... \
        --remote-idle-seconds 1080

`--pack` is not optional window dressing: more than one pack now lives in `backend/packs/`
and the loader refuses to guess which rulebook governs a run. With `active_pack_id` set in
the config store the flag can be omitted; with it unset and two packs present this harness
refuses and names them, rather than measuring a corpus against whichever pack sorted first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from backend.adapters import extract_document
from backend.adapters.base import AdapterResult
from backend.engine import packs as packs_module
from backend.engine import rounds as rounds_module
from backend.engine.config import DEFAULT_TENANT, control, load_env
from backend.engine.contracts import RoundReport
from backend.eval import score as score_module
from backend.memory.precedents import SqlitePrecedentStore
from backend.pipeline import process_document

# Imported rather than copied: this table is the service's own suffix-to-media-type
# dispatch, and a harness that measured a different dispatch than the product uses would
# be measuring a path nobody ships. If this import ever breaks, the harness must fail
# loudly rather than quietly measure something else.
from backend.api.persisted import _SUFFIX_TO_MEDIA_TYPE as SUFFIX_TO_MEDIA_TYPE

#: Bumped by hand when a measured quantity changes meaning, so two artifacts that cannot
#: be compared are detectable rather than merely different.
HARNESS_VERSION = "1"

GENERATED = Path(__file__).resolve().parent / "generated"
DEFAULT_ARTIFACT = Path(__file__).resolve().parent / "performance.json"

#: `ground_truth.json` is the answer key, not a document to ingest.
_NOT_A_DOCUMENT = frozenset({".json"})

#: Read-only endpoints. Nothing here writes to the deployed service -- see the docstring.
REMOTE_ENDPOINTS: tuple[str, ...] = ("/api/health", "/api/packs")

#: Fields in the artifact that are stopwatch readings and therefore differ on every run.
#: Everything else is expected to be bit-identical for the same documents and pack.
TIMING_FIELDS: tuple[str, ...] = (
    "local.documents[].extract_ms",
    "local.documents[].map_ms",
    "local.documents[].total_ms",
    "local.wall_clock_ms",
    "local.slowest_document_ms",
    "local.fields_per_second",
    "remote.cold_start_ms",
    "remote.endpoints[].samples_ms",
    "remote.endpoints[].min_ms",
    "remote.endpoints[].median_ms",
    "remote.endpoints[].max_ms",
    "generated_at",
)


# --- Boundary types -----------------------------------------------------------


class AccuracyStatement(BaseModel):
    """Whether accuracy was measured, and if not, the scorer's own refusal verbatim.

    Required on `PerformanceReport` on purpose: the only number in the round report that
    could be mistaken for a measurement is `mapping_accuracy`, and this block is what makes
    reading it without the refusal impossible.
    """

    model_config = ConfigDict(extra="forbid")

    measured: bool
    mapping_accuracy: float | None
    conversion_correctness: float | None
    confirmed_rows: int
    required_rows: int
    total_rows: int
    #: The one sentence a reader must not be able to skip.
    statement: str
    #: `score.Unscoreable.reason` unaltered, or None once the golden set is confirmed.
    scorer_refusal: str | None = None


class CostStatement(BaseModel):
    """Tokens are counted. Dollars are not convertible here, and that is stated."""

    model_config = ConfigDict(extra="forbid")

    tokens_charged: int
    model_calls_made: int
    model_calls_skipped: int
    cost_usd: float
    cost_usd_basis: str
    tokens_basis: str


class DocumentMeasurement(BaseModel):
    """One document: what it cost, what it produced, and what it could not report."""

    model_config = ConfigDict(extra="forbid")

    name: str
    sha256_16: str
    bytes: int
    media_type: str
    extraction_status: str
    extraction_engine: str | None
    #: None for a format that has no pages. Never 1 as a stand-in -- see `page_count_basis`.
    page_count: int | None
    page_count_basis: str
    facts_extracted: int
    #: Reportable fields, i.e. rows the review tray and the gold table can hold.
    fields_reported: int
    auto_accepted: int
    flagged: int
    missing: int
    not_reportable: int
    model_calls_made: int
    model_calls_skipped: int
    precedents_applied: int
    tokens_charged: int
    extract_ms: float
    map_ms: float
    total_ms: float
    #: Named, not swallowed: a document that produced nothing says why here.
    note: str | None = None


class LocalRun(BaseModel):
    """The in-process run. Never averaged with a remote number."""

    model_config = ConfigDict(extra="forbid")

    environment: str = "local-in-process"
    what_is_timed: str
    excluded_from_the_timing: str
    model_access: str
    python: str
    platform: str
    documents: list[DocumentMeasurement]
    documents_measured: int
    documents_unreadable: int
    pages_counted: int
    pages_not_applicable: int
    facts_extracted: int
    fields_reported: int
    auto_accepted: int
    flagged: int
    missing: int
    not_reportable: int
    precedents_available: int
    precedents_applied: int
    model_calls_made: int
    model_calls_skipped: int
    tokens_charged: int
    wall_clock_ms: float
    slowest_document: str
    slowest_document_ms: float
    fields_per_second: float


class RemoteEndpointProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    status_codes: list[int]
    samples_ms: list[float]
    min_ms: float | None
    median_ms: float | None
    max_ms: float | None
    attempts: int
    #: Honest retry accounting: the local network drops outbound connections, and a sample
    #: that took three attempts is not the same evidence as one that took one.
    retries: int
    failures: list[str]


class RemoteProbe(BaseModel):
    """HTTP round-trip latency against the deployed revision. Not pipeline latency."""

    model_config = ConfigDict(extra="forbid")

    environment: str = "cloud-run-deployed"
    base_url: str
    #: Recorded as DECLARED by the operator on the command line. Not measured from the wire.
    revision_declared: str | None
    region_declared: str | None
    min_instances_declared: int | None
    what_is_timed: str
    method: str = "GET only"
    cold_start_ms: float | None
    cold_start_basis: str
    warm_latency_basis: str
    per_document_latency: str
    endpoints: list[RemoteEndpointProbe]
    reachable: bool
    unreachable_reason: str | None = None


class PerformanceReport(BaseModel):
    """The artifact. A real RoundReport, plus the refusals that keep it readable."""

    model_config = ConfigDict(extra="forbid")

    harness_version: str = HARNESS_VERSION
    generated_at: str
    round_report: RoundReport
    #: Required. A performance report without an accuracy statement is the failure mode
    #: this file exists to prevent.
    accuracy: AccuracyStatement
    cost: CostStatement
    local: LocalRun
    remote: RemoteProbe | None = None
    controlled_variables: dict[str, str] = Field(default_factory=dict)
    timing_fields: list[str] = Field(default_factory=lambda: list(TIMING_FIELDS))
    determinism: str = (
        "the same documents and pack produce the same lane counts, fact counts and "
        "fingerprint on every run; only the fields listed in timing_fields vary"
    )


# --- The six controlled variables ---------------------------------------------


def sampling_sent(seam: object | None) -> str:
    """What sampling actually went on the wire. Never what was intended.

    The string is a controlled variable, so it has to describe the wire. With no seam no
    request exists at all, which is a third case distinct from "temperature=0" and from
    "the provider removed it": saying `temperature=0` for a run that sent nothing would be
    a false claim about a controlled variable, exactly as it would be for the Anthropic
    dialect, which rejects the parameter outright.
    """
    if seam is None:
        return (
            "not-sent: no request was made (no provider seam was configured, so the "
            "mapper consulted no model)"
        )
    shaped = getattr(seam, "last_request", None)
    if shaped is None:
        return "not-sent: a seam was configured but no request was ever shaped"
    if shaped.temperature_sent is not None:
        return f"temperature={shaped.temperature_sent}"
    return f"not-sent: removed by provider ({shaped.omission_reason})"


def _resolved(key: str, *, tenant_id: str) -> tuple[str, str]:
    """(value, source). The source is recorded because a control's origin is evidence."""
    answer = control(key, tenant_id=tenant_id)
    return str(answer.value), str(getattr(answer.source, "value", answer.source))


# --- Local, in-process --------------------------------------------------------


def documents_on_disk(directory: Path = GENERATED) -> list[Path]:
    """The generated corpus, sorted, with the answer key excluded."""
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() not in _NOT_A_DOCUMENT
    )


def _page_basis(result: AdapterResult, media_type: str) -> str:
    if result.page_count is not None:
        return f"measured: {result.engine or 'the adapter'} reported the page count"
    return (
        f"not applicable: {media_type} is not paginated, so the adapter reports no page "
        "count and this harness does not substitute 1"
    )


def _note_for(result: AdapterResult, facts: int, reported: int) -> str | None:
    if result.status != "done":
        return f"{result.status}: {result.error or 'the adapter gave no reason'}"
    if facts == 0:
        return (
            "the text adapter returned done with zero facts: this file carries no text "
            "layer, and the service path dispatches a PDF to adapters/pdf_text only -- it "
            "does not fall back to adapters/pdf_scan, whose default pixel reader returns "
            "Unavailable. So this document contributes no fields to any run today. That is "
            "a gap in the ingestion path, not a measurement of zero latency"
        )
    if reported == 0:
        return "facts were extracted but none of their labels is a reportable field"
    return None


def measure_locally(
    paths: Sequence[Path],
    *,
    pack: packs_module.Pack,
    precedents: SqlitePrecedentStore,
    seam: object | None,
    tenant_id: str = DEFAULT_TENANT,
) -> tuple[LocalRun, list[str]]:
    """Run each document through the real path with a stopwatch. Returns (run, hashes)."""
    measurements: list[DocumentMeasurement] = []
    hashes: list[str] = []
    run_started = time.perf_counter()

    for index, path in enumerate(paths):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        hashes.append(digest)
        media_type = SUFFIX_TO_MEDIA_TYPE.get(
            path.suffix.lower(), "application/octet-stream"
        )
        document_id = f"measure-{index}-{digest[:8]}"

        extract_started = time.perf_counter()
        result = extract_document(data, media_type, document_id=document_id)
        extract_ms = (time.perf_counter() - extract_started) * 1000.0

        map_ms = 0.0
        auto = flagged = missing = 0
        fields_reported = not_reportable = 0
        calls_made = calls_skipped = applied = 0
        if result.status == "done" and result.facts:
            map_started = time.perf_counter()
            outcome = process_document(
                document_id,
                result.facts,
                pack=pack,
                precedents=precedents,
                seam=seam,
                tenant_id=tenant_id,
                document_name=path.name,
            )
            map_ms = (time.perf_counter() - map_started) * 1000.0
            auto, flagged, missing = rounds_module.count_lanes(outcome.mappings)
            fields_reported = len(outcome.resolutions)
            not_reportable = len(outcome.not_reportable)
            calls_made = outcome.counters.model_calls_made
            calls_skipped = outcome.counters.model_calls_skipped
            applied = outcome.counters.precedents_applied

        # Tokens are read off the seam's own budget, which is the only thing that knows
        # what a provider charged. With no seam the figure is a counted zero.
        budget = getattr(seam, "budget", None) if seam is not None else None
        tokens = int(getattr(budget, "spent", 0) or 0)

        measurements.append(
            DocumentMeasurement(
                name=path.name,
                sha256_16=digest[:16],
                bytes=len(data),
                media_type=media_type,
                extraction_status=result.status,
                extraction_engine=result.engine,
                page_count=result.page_count,
                page_count_basis=_page_basis(result, media_type),
                facts_extracted=len(result.facts),
                fields_reported=fields_reported,
                auto_accepted=auto,
                flagged=flagged,
                missing=missing,
                not_reportable=not_reportable,
                model_calls_made=calls_made,
                model_calls_skipped=calls_skipped,
                precedents_applied=applied,
                tokens_charged=tokens,
                extract_ms=round(extract_ms, 3),
                map_ms=round(map_ms, 3),
                total_ms=round(extract_ms + map_ms, 3),
                note=_note_for(result, len(result.facts), fields_reported),
            )
        )

    wall_ms = (time.perf_counter() - run_started) * 1000.0
    slowest = max(measurements, key=lambda m: m.total_ms, default=None)
    fields = sum(m.fields_reported for m in measurements)

    run = LocalRun(
        what_is_timed=(
            "extract_ms is the format adapter; map_ms is pipeline.process_document, which "
            "is retrieval, mapping, unit conversion and the gate; total_ms is their sum"
        ),
        excluded_from_the_timing=(
            "HTTP, JSON serialization, sqlite persistence, the evidence ledger and the "
            "export renderer. This is pipeline latency, not end-to-end API latency, and "
            "the two must not be quoted as one another"
        ),
        model_access=(
            "no provider seam was configured, so the pipeline made zero model calls. That "
            "zero is a configuration fact, not an efficiency result: everything the pack "
            "declares resolves deterministically and every ambiguous label goes to the "
            "review tray, which is the configuration the product promises works"
            if seam is None
            else "a provider seam was configured, so model calls in this run were live"
        ),
        python=platform.python_version(),
        platform=platform.platform(terse=True),
        documents=measurements,
        documents_measured=len(measurements),
        documents_unreadable=sum(
            1 for m in measurements if m.extraction_status not in ("done",)
        ),
        pages_counted=sum(m.page_count or 0 for m in measurements),
        pages_not_applicable=sum(1 for m in measurements if m.page_count is None),
        facts_extracted=sum(m.facts_extracted for m in measurements),
        fields_reported=fields,
        auto_accepted=sum(m.auto_accepted for m in measurements),
        flagged=sum(m.flagged for m in measurements),
        missing=sum(m.missing for m in measurements),
        not_reportable=sum(m.not_reportable for m in measurements),
        precedents_available=len(precedents.all_precedents(tenant_id)),
        precedents_applied=sum(m.precedents_applied for m in measurements),
        model_calls_made=sum(m.model_calls_made for m in measurements),
        model_calls_skipped=sum(m.model_calls_skipped for m in measurements),
        tokens_charged=sum(m.tokens_charged for m in measurements),
        wall_clock_ms=round(wall_ms, 3),
        slowest_document=slowest.name if slowest else "",
        slowest_document_ms=slowest.total_ms if slowest else 0.0,
        fields_per_second=round(fields / (wall_ms / 1000.0), 2) if wall_ms > 0 else 0.0,
    )
    return run, hashes


# --- The deployed service, read-only ------------------------------------------


def _time_one_get(url: str, *, timeout_s: float) -> tuple[float, int]:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "canon-eval"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        response.read()
        status = int(response.status)
    return (time.perf_counter() - started) * 1000.0, status


def probe_endpoint(
    base_url: str, path: str, *, samples: int, retries: int, timeout_s: float
) -> RemoteEndpointProbe:
    """Time N GETs, retrying a dropped connection and counting the retries.

    Retries are reported rather than absorbed: this network drops outbound connections
    intermittently, and "reachable on the third attempt" is a different fact from
    "reachable", which is why the count is in the artifact.
    """
    url = base_url.rstrip("/") + path
    took: list[float] = []
    codes: list[int] = []
    failures: list[str] = []
    attempts = retried = 0

    for _ in range(samples):
        for attempt in range(retries + 1):
            attempts += 1
            if attempt:
                retried += 1
            try:
                elapsed, status = _time_one_get(url, timeout_s=timeout_s)
            except urllib.error.HTTPError as exc:
                # An HTTP error is a real reply and its round trip is a real measurement.
                failures.append(f"HTTP {exc.code}")
                codes.append(int(exc.code))
                break
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
                continue
            took.append(round(elapsed, 3))
            codes.append(status)
            break

    return RemoteEndpointProbe(
        path=path,
        status_codes=codes,
        samples_ms=took,
        min_ms=round(min(took), 3) if took else None,
        median_ms=round(statistics.median(took), 3) if took else None,
        max_ms=round(max(took), 3) if took else None,
        attempts=attempts,
        retries=retried,
        failures=failures,
    )


def probe_remote(
    base_url: str,
    *,
    samples: int = 5,
    retries: int = 4,
    timeout_s: float = 60.0,
    idle_seconds: int | None = None,
    revision: str | None = None,
    region: str | None = None,
    min_instances: int | None = None,
) -> RemoteProbe:
    """Measure the deployed revision with GETs only, cold start kept separate.

    `idle_seconds` is the operator asserting the instance had scaled to zero before the
    first request. Without that assertion there is no way to know whether the first sample
    booted a container, so `cold_start_ms` stays null rather than being filled with a
    number that might be either thing.
    """
    first = probe_endpoint(
        base_url, REMOTE_ENDPOINTS[0], samples=1, retries=retries, timeout_s=timeout_s
    )
    first_ms = first.samples_ms[0] if first.samples_ms else None

    if first_ms is None:
        return RemoteProbe(
            base_url=base_url,
            revision_declared=revision,
            region_declared=region,
            min_instances_declared=min_instances,
            what_is_timed="nothing: the service did not answer",
            cold_start_ms=None,
            cold_start_basis="not measured: the service did not answer",
            warm_latency_basis="not measured: the service did not answer",
            per_document_latency=_REMOTE_PER_DOC,
            endpoints=[first],
            reachable=False,
            unreachable_reason=(
                f"{first.attempts} attempt(s), all failed: {'; '.join(first.failures[:3])}"
            ),
        )

    if idle_seconds:
        cold_ms: float | None = first_ms
        cold_basis = (
            f"measured: the first GET after a verified idle window of {idle_seconds}s, "
            f"against a min-instances-0 revision. This is a container boot plus one "
            f"request, NOT latency, and must never be averaged with the warm samples"
        )
    else:
        cold_ms = None
        cold_basis = (
            "not measured: no idle window was asserted, so there is no way to know whether "
            f"the first request ({first_ms} ms) booted a container or hit a live one. Pass "
            "--remote-idle-seconds after waiting out the idle window to measure it"
        )

    endpoints = [
        probe_endpoint(base_url, path, samples=samples, retries=retries, timeout_s=timeout_s)
        for path in REMOTE_ENDPOINTS
    ]

    return RemoteProbe(
        base_url=base_url,
        revision_declared=revision,
        region_declared=region,
        min_instances_declared=min_instances,
        what_is_timed=(
            "wall-clock time for one HTTPS GET from this machine, connection setup to last "
            "byte. It includes the public internet and TLS, so it is an upper bound on "
            "server time and not a server-side measurement"
        ),
        cold_start_ms=cold_ms,
        cold_start_basis=cold_basis,
        warm_latency_basis=(
            f"measured: {samples} GET(s) per endpoint taken after the first request above, "
            "so the container was already running. Reported as min/median/max, never "
            "averaged with the cold start"
        ),
        per_document_latency=_REMOTE_PER_DOC,
        endpoints=[first, *endpoints],
        reachable=True,
    )


#: Why there is no remote per-document number, stated once and carried into the artifact.
_REMOTE_PER_DOC = (
    "NOT MEASURED. Per-document latency on the deployed service would require POSTing the "
    "corpus to /api/batches, and that revision reports a provider key present in its "
    "config store -- so the upload would make live billable model calls and would write "
    "rows into the demo's database. Neither is a measurement this harness is willing to "
    "take. Remote numbers here are read-only HTTP round trips; per-document pipeline cost "
    "is the local figure"
)


# --- Assembling the report ----------------------------------------------------


def accuracy_statement(outcome: object) -> AccuracyStatement:
    """Turn the scorer's answer -- a Score or its refusal -- into one unskippable block."""
    if isinstance(outcome, score_module.Unscoreable):
        return AccuracyStatement(
            measured=False,
            mapping_accuracy=None,
            conversion_correctness=None,
            confirmed_rows=outcome.confirmed,
            required_rows=outcome.required,
            total_rows=outcome.total_rows,
            statement=(
                "MAPPING ACCURACY IS NOT MEASURED. "
                f"{outcome.confirmed} of {outcome.required} required golden rows are "
                "confirmed, so backend/eval/score.py refused to produce a figure and this "
                "harness has none to report. The 0.0 in round_report.mapping_accuracy and "
                "round_report.conversion_correctness is a placeholder forced by the "
                "contract's float type -- it is NOT a measurement and must not be quoted "
                "as one. Latency, lane counts and token cost in this report ARE measured."
            ),
            scorer_refusal=outcome.reason,
        )

    score = outcome  # a real Score
    return AccuracyStatement(
        measured=True,
        mapping_accuracy=score.mapping_accuracy,  # type: ignore[union-attr]
        conversion_correctness=score.conversion_correctness,  # type: ignore[union-attr]
        confirmed_rows=score.confirmed,  # type: ignore[union-attr]
        required_rows=score_module.MINIMUM_CONFIRMED_ROWS,
        total_rows=score.confirmed,  # type: ignore[union-attr]
        statement=(
            f"Measured against {score.confirmed} confirmed golden rows, "  # type: ignore[union-attr]
            f"{score.unmatched} of which the pipeline produced no mapping for and which "  # type: ignore[union-attr]
            "therefore count as wrong."
        ),
        scorer_refusal=None,
    )


def build_report(
    *,
    paths: Sequence[Path],
    pack: packs_module.Pack,
    precedents: SqlitePrecedentStore,
    seam: object | None,
    tenant_id: str,
    round_number: int,
    remote: RemoteProbe | None,
    previous: RoundReport | None = None,
) -> PerformanceReport:
    local, hashes = measure_locally(
        paths, pack=pack, precedents=precedents, seam=seam, tenant_id=tenant_id
    )

    mappings_were_scored = score_module.score([])
    accuracy = accuracy_statement(mappings_were_scored)

    provider, provider_source = _resolved("provider", tenant_id=tenant_id)
    model, model_source = _resolved("model", tenant_id=tenant_id)
    prompt_version, prompt_source = _resolved("prompt_version", tenant_id=tenant_id)
    minutes_raw, minutes_source = _resolved("analyst_minutes_per_field", tenant_id=tenant_id)
    sampling = sampling_sent(seam)

    report = RoundReport(
        round=round_number,
        tenant_id=tenant_id,
        pack_id=pack.id,
        pack_version=pack.version,
        provider=provider,
        model=model,
        sampling=sampling,
        prompt_version=prompt_version,
        documents_fingerprint=rounds_module.fingerprint_documents(hashes),
        docs=local.documents_measured,
        fields=local.fields_reported,
        auto_accepted=local.auto_accepted,
        flagged=local.flagged,
        missing=local.missing,
        # Placeholders, and unreadable without `accuracy` above. See the module docstring.
        mapping_accuracy=accuracy.mapping_accuracy or 0.0,
        conversion_correctness=accuracy.conversion_correctness or 0.0,
        precedents_applied=local.precedents_applied,
        model_calls_skipped=local.model_calls_skipped,
        analyst_minutes_saved=rounds_module.analyst_minutes_saved(
            local.auto_accepted, float(minutes_raw)
        ),
        cost_usd=0.0,
    )

    return PerformanceReport(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        round_report=rounds_module.compare(report, previous),
        accuracy=accuracy,
        cost=CostStatement(
            tokens_charged=local.tokens_charged,
            model_calls_made=local.model_calls_made,
            model_calls_skipped=local.model_calls_skipped,
            cost_usd=0.0,
            cost_usd_basis=(
                "measured as zero because zero tokens were charged: no provider seam was "
                "configured, so no request was sent. The dollars-per-token conversion is "
                "NOT available -- this repository holds no price table -- so a run that "
                "did charge tokens would report the token count and leave cost_usd at 0.0 "
                "with this same note rather than estimate a price"
                if local.tokens_charged == 0
                else "NOT MEASURED: tokens were charged but this repository holds no price "
                "table, so the token count above is the honest cost figure and the dollar "
                "amount is unavailable rather than estimated"
            ),
            tokens_basis=(
                "read from the seam's own TokenBudget, which is the only counter that sees "
                "what a provider reported as usage"
            ),
        ),
        local=local,
        remote=remote,
        controlled_variables={
            "documents_fingerprint": (
                f"{report.documents_fingerprint} (sha256 over "
                f"{local.documents_measured} document(s), order-independent)"
            ),
            "pack_version": f"{pack.id} {pack.version} (source=packs/)",
            "provider": f"{provider} (source={provider_source})",
            "model": f"{model} (source={model_source})",
            "sampling": sampling,
            "prompt_version": f"{prompt_version} (source={prompt_source})",
            "analyst_minutes_per_field": (
                f"{minutes_raw} (source={minutes_source}); not a controlled variable, "
                "recorded because analyst_minutes_saved is derived from it"
            ),
        },
    )


# --- Human-readable rendering -------------------------------------------------


def render(report: PerformanceReport) -> str:
    """A terminal summary. Prints NOT MEASURED where there is no measurement."""
    lines: list[str] = []
    local = report.local
    out = lines.append

    out("CANON PERFORMANCE MEASUREMENT")
    out(f"  harness v{report.harness_version}   generated {report.generated_at}")
    out("")
    out("CONTROLLED VARIABLES (all six, or rounds.compare() refuses a delta)")
    for key in rounds_module.CONTROLLED_VARIABLES:
        out(f"  {key:24s} {report.controlled_variables.get(key, getattr(report.round_report, key))}")
    out("")
    out(f"LOCAL, IN-PROCESS -- {local.what_is_timed}")
    out(f"  excluded: {local.excluded_from_the_timing}")
    out(f"  model access: {local.model_access}")
    out("")
    header = (
        f"  {'document':40s} {'pages':>5s} {'facts':>6s} {'fields':>6s} "
        f"{'auto':>5s} {'rev':>5s} {'miss':>5s} {'extract':>9s} {'map':>9s} {'total':>9s}"
    )
    out(header)
    for doc in local.documents:
        pages = str(doc.page_count) if doc.page_count is not None else "n/a"
        out(
            f"  {doc.name[:40]:40s} {pages:>5s} {doc.facts_extracted:>6d} "
            f"{doc.fields_reported:>6d} {doc.auto_accepted:>5d} {doc.flagged:>5d} "
            f"{doc.missing:>5d} {doc.extract_ms:>8.1f}m {doc.map_ms:>8.1f}m "
            f"{doc.total_ms:>8.1f}m"
        )
    out("")
    for doc in local.documents:
        if doc.note:
            out(f"  ! {doc.name}: {doc.note}")
        if doc.page_count is None:
            out(f"  - {doc.name}: pages {doc.page_count_basis}")
    out("")
    out(
        f"  TOTAL  {local.documents_measured} document(s), {local.pages_counted} counted "
        f"page(s) ({local.pages_not_applicable} file(s) not paginated), "
        f"{local.facts_extracted} fact(s), {local.fields_reported} reportable field(s)"
    )
    out(
        f"  LANES  auto {local.auto_accepted} / review {local.flagged} / missing "
        f"{local.missing}   (+{local.not_reportable} label(s) not reportable, counted "
        "never queued)"
    )
    out(
        f"  WALL   {local.wall_clock_ms:.1f} ms for the corpus; slowest "
        f"{local.slowest_document} at {local.slowest_document_ms:.1f} ms; "
        f"{local.fields_per_second} field(s)/second"
    )
    out(
        f"  LOOP   precedents available {local.precedents_available}, applied "
        f"{local.precedents_applied}; model calls made {local.model_calls_made}, skipped "
        f"{local.model_calls_skipped}"
    )
    out(
        f"  EFFORT {report.round_report.analyst_minutes_saved} analyst minute(s) saved, "
        "from the pipeline's auto-accept counter via rounds.analyst_minutes_saved()"
    )
    out("")
    out("COST")
    out(f"  tokens charged  {report.cost.tokens_charged}")
    out(f"  model calls     {report.cost.model_calls_made} made, {report.cost.model_calls_skipped} skipped")
    out(f"  cost_usd        {report.cost.cost_usd}  <- {report.cost.cost_usd_basis}")
    out("")
    out("ACCURACY")
    if report.accuracy.measured:
        out(f"  mapping_accuracy        {report.accuracy.mapping_accuracy}")
        out(f"  conversion_correctness  {report.accuracy.conversion_correctness}")
        out(f"  {report.accuracy.statement}")
    else:
        out("  mapping_accuracy        NOT MEASURED")
        out("  conversion_correctness  NOT MEASURED")
        out(
            f"  {report.accuracy.confirmed_rows} of {report.accuracy.required_rows} "
            f"golden rows confirmed ({report.accuracy.total_rows} rows exist)"
        )
        out(f"  scorer's refusal: {report.accuracy.scorer_refusal}")
        out(f"  {report.accuracy.statement}")
    out("")
    remote = report.remote
    if remote is None:
        out("DEPLOYED SERVICE -- not probed (pass --remote URL)")
    else:
        out(f"DEPLOYED SERVICE -- {remote.base_url}")
        out(
            f"  revision {remote.revision_declared} / region {remote.region_declared} / "
            f"min-instances {remote.min_instances_declared}  (declared, not measured)"
        )
        out(f"  timed: {remote.what_is_timed}")
        if remote.cold_start_ms is None:
            out("  cold start      NOT MEASURED")
        else:
            out(f"  cold start      {remote.cold_start_ms:.1f} ms  (ONE sample, kept separate)")
        out(f"    {remote.cold_start_basis}")
        for endpoint in remote.endpoints:
            if endpoint.min_ms is None:
                out(
                    f"  {endpoint.path:14s} NO SAMPLE: {endpoint.attempts} attempt(s), "
                    f"{endpoint.retries} retry/retries, {'; '.join(endpoint.failures[:2])}"
                )
                continue
            out(
                f"  {endpoint.path:14s} min {endpoint.min_ms:8.1f} / median "
                f"{endpoint.median_ms:8.1f} / max {endpoint.max_ms:8.1f} ms  "
                f"[{len(endpoint.samples_ms)} sample(s), {endpoint.attempts} attempt(s), "
                f"{endpoint.retries} retry/retries, {len(endpoint.failures)} failure(s)]"
            )
        out(f"  per-document latency: {remote.per_document_latency}")
    out("")
    out(f"COMPARABLE: {report.round_report.comparable}")
    if report.round_report.not_comparable_reason:
        out(f"  {report.round_report.not_comparable_reason}")
    if report.round_report.delta_vs_previous:
        out(f"  delta vs previous: {report.round_report.delta_vs_previous}")
    out("")
    out("TIMING FIELDS (these and only these differ between two runs of the same corpus)")
    for field_path in report.timing_fields:
        out(f"  {field_path}")
    return "\n".join(lines)


# --- Entry point --------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m backend.eval.measure",
        description="Measure pipeline latency, throughput and token cost. Names what it cannot measure.",
    )
    parser.add_argument("--documents", default=str(GENERATED), help="corpus directory")
    parser.add_argument(
        "--pack",
        default=None,
        help="which pack governs this run; defaults to the configured active_pack_id, and "
        "there is no fallback -- see the module docstring on why guessing is refused",
    )
    parser.add_argument("--out", default=str(DEFAULT_ARTIFACT), help="JSON artifact path")
    parser.add_argument("--round", type=int, default=1, dest="round_number")
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    parser.add_argument(
        "--previous",
        default=None,
        help="an earlier artifact to compare against; the six controlled variables must match",
    )
    parser.add_argument(
        "--allow-model-calls",
        action="store_true",
        help="opt in to a live seam. Off by default: a key in the config store would "
        "otherwise make this harness bill the operator on every ambiguous label.",
    )
    parser.add_argument("--remote", default=None, help="base URL of a deployed service")
    parser.add_argument("--remote-samples", type=int, default=5)
    parser.add_argument("--remote-retries", type=int, default=4)
    parser.add_argument("--remote-timeout-s", type=float, default=60.0)
    parser.add_argument(
        "--remote-idle-seconds",
        type=int,
        default=None,
        help="assert the instance was idle this long, so the first GET is a real cold start",
    )
    parser.add_argument("--remote-revision", default=None)
    parser.add_argument("--remote-region", default=None)
    parser.add_argument("--remote-min-instances", type=int, default=None)
    return parser.parse_args(argv)


def _previous_report(path: str | None) -> RoundReport | None:
    if not path:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return RoundReport.model_validate(raw["round_report"])


def load_environment() -> list[str]:
    """Call `load_env()` for every place a .env legitimately lives. Entry point only.

    Spelled out here rather than imported from `backend.api.main`, which would drag the web
    framework into the eval package for four lines -- and `tests/test_env_is_loaded.py`
    looks for a literal `load_env(` call anyway, because a wrapper it cannot see is
    indistinguishable from no call at all. The resolved controls in this report are the
    round's controlled variables, so a `.env` that nothing read would mean the report named
    a provider and a model the run did not use.
    """
    root = Path(__file__).resolve().parents[2]
    loaded: list[str] = []
    for candidate in (root / ".env", root / "backend" / ".env"):
        if load_env(candidate):
            loaded.append(str(candidate))
    return loaded


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    for env_file in load_environment():
        print(f"loaded {env_file}", file=sys.stderr)

    paths = documents_on_disk(Path(args.documents))
    if not paths:
        print(
            f"no documents in {args.documents}: run python -m backend.eval.make_documents",
            file=sys.stderr,
        )
        return 2

    wanted = args.pack or (control("active_pack_id", tenant_id=args.tenant).value or "")
    try:
        pack = packs_module.resolve_active_pack(wanted)
    except packs_module.PackError as exc:
        # The run is blocked before a document is read, naming the problem (CLAUDE.md 6).
        # A harness that picked a pack for the operator would be measuring a corpus against
        # a rulebook nobody chose, and the lane counts would be meaningless.
        print(f"no pack governs this run: {exc}", file=sys.stderr)
        print("pass --pack <id>, or set active_pack_id in the config store.", file=sys.stderr)
        return 2

    seam = None
    if args.allow_model_calls:
        from backend.intelligence.base import Seam, httpx_transport

        seam = Seam.from_config(transport=httpx_transport(), tenant_id=args.tenant)

    remote = None
    if args.remote:
        remote = probe_remote(
            args.remote,
            samples=args.remote_samples,
            retries=args.remote_retries,
            timeout_s=args.remote_timeout_s,
            idle_seconds=args.remote_idle_seconds,
            revision=args.remote_revision,
            region=args.remote_region,
            min_instances=args.remote_min_instances,
        )

    # A throwaway precedent store: the corpus must not be measured against whatever a
    # previous demo happened to teach, or the lane counts stop being reproducible.
    # `ignore_cleanup_errors` because the store holds its sqlite handle open and Windows
    # refuses to unlink an open file -- a failure to delete a scratch file must not throw
    # away a completed measurement.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workspace:
        report = build_report(
            paths=paths,
            pack=pack,
            precedents=SqlitePrecedentStore(Path(workspace) / "memory.db"),
            seam=seam,
            tenant_id=args.tenant,
            round_number=args.round_number,
            remote=remote,
            previous=_previous_report(args.previous),
        )

    print(render(report))
    destination = Path(args.out)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nartifact written: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
