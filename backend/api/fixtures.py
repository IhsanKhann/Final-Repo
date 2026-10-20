"""The PipelineService the API runs on until the engine is wired in.

Exists so the twelve endpoints are testable and the frontend can run against a real HTTP
server today, with `VITE_USE_MOCK=false`, while `engine/{units,resolve,gate,ledger}.py` is
still being written. It is a mirror of `Frontend/src/api/mockData.ts` -- the fixture the UI
was built against -- stored through the real `Repository` so that corrections persist and
the swap to the real engine removes this file rather than rearranging the routes.

This module is also the ONLY place in `backend/api/` that contains sample-domain nouns.
That is on purpose: they are a demo payload, not meaning, and keeping them in one file
means a grep hit has exactly one home and deleting the fixture is deleting one import.

What this module refuses to do:
  * It refuses to randomise. `learned` is a stated rule over the mapping's prior status,
    not a coin flip, because a feedback-loop claim that varies per request is a lie the
    demo cannot survive.
  * It refuses to construct a value without provenance -- it cannot, `contracts.Mapping`
    forbids it -- and it refuses to approve a mapping that has none, downgrading instead.
  * It refuses to raise. Absence is `None`; a storage failure degrades the answer.
  * It refuses to claim the engine is ready. `health_layers()` reports this service as
    `degraded` with the reason, so nobody demos a fixture believing it is the backbone.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from backend.api.deps import ExportFile, UploadedFile
from backend.api.eventlog import EventLog, new_event
from backend.api.repository import Repository
from backend.engine.config import DEFAULT_TENANT
from backend.engine.contracts import (
    AgentEvent,
    Batch,
    BatchFile,
    BatchStats,
    BulkAcceptPayload,
    BulkAcceptResponse,
    Conversion,
    CreateBatchPayload,
    DatasetRecord,
    Document,
    FeedbackEvent,
    HealthLayer,
    HomeStats,
    InsightRun,
    Insights,
    LearnedCorrection,
    Mapping,
    MappingPatchPayload,
    MappingPatchResponse,
    PaginatedResponse,
    ReviewQueueItem,
    SchemaField,
    SchemaPack,
    SourceLocationPdf,
    SourceLocationSheet,
    SourceLocationText,
    UnitConversion,
    ValidationResult,
)

__all__ = ["FixtureService"]

#: Statuses that keep a field in the analyst's tray. The middle lane is the interesting
#: one, so it is named here once rather than spelled out at four call sites.
OPEN_STATUSES: tuple[str, ...] = ("review", "missing")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- The fixture payload ------------------------------------------------------
# Mirrors Frontend/src/api/mockData.ts. Ids match so a frontend deep link still resolves.


def _packs() -> list[SchemaPack]:
    return [
        SchemaPack(
            id="mining-v1",
            name="Mining",
            version="1.0",
            description="Metals & mining production reports",
            fields=[
                SchemaField(
                    name="production_t",
                    label="Production (t)",
                    type="number",
                    unit="t",
                    required=True,
                    synonyms=["output", "yield", "production"],
                ),
                SchemaField(
                    name="unit_cost",
                    label="Unit Cost ($/t)",
                    type="number",
                    unit="$/t",
                    required=True,
                    synonyms=["cash cost", "opex", "cost per unit"],
                ),
                SchemaField(
                    name="site_name",
                    label="Site Name",
                    type="string",
                    required=True,
                    synonyms=["mine name", "operation", "project"],
                ),
                SchemaField(
                    name="period",
                    label="Reporting Period",
                    type="string",
                    required=True,
                    synonyms=["quarter", "period", "date range"],
                ),
            ],
            conversions=[
                UnitConversion(
                    id="lb-t", from_unit="lb", to_unit="t", factor=0.000453592,
                    formula="value x 0.000453592",
                ),
                UnitConversion(
                    id="usd-lb-usd-t", from_unit="$/lb", to_unit="$/t", factor=2204.62,
                    formula="value x 2204.62",
                ),
            ],
            rules=[],
            updated_at="2026-10-15T10:00:00Z",
        ),
        SchemaPack(
            id="shipping-v1",
            name="Shipping",
            version="1.0",
            description="Freight & logistics tariff tables",
            fields=[
                SchemaField(
                    name="freight_rate",
                    label="Freight Rate ($/TEU)",
                    type="number",
                    unit="$/TEU",
                    required=True,
                    synonyms=["rate", "tariff", "freight cost"],
                ),
                SchemaField(
                    name="origin_port",
                    label="Origin Port",
                    type="string",
                    required=True,
                    synonyms=["from", "departure", "POL"],
                ),
                SchemaField(
                    name="transit_days",
                    label="Transit Time (days)",
                    type="number",
                    required=False,
                    synonyms=["transit", "sailing time"],
                ),
            ],
            conversions=[],
            rules=[],
            updated_at="2026-10-14T08:00:00Z",
        ),
    ]


def _documents() -> list[Document]:
    return [
        Document(
            id="doc-001", batch_id="batch-001", name="rates_q3.xlsx", type="xlsx",
            file_url="/files/doc-001", status="done", created_at="2026-10-19T08:02:00Z",
        ),
        Document(
            id="doc-002", batch_id="batch-001", name="filing.pdf", type="pdf",
            file_url="/files/doc-002", page_count=12, status="done",
            created_at="2026-10-19T08:03:00Z",
        ),
        Document(
            id="doc-003", batch_id="batch-001", name="notes.html", type="html",
            file_url="/files/doc-003", status="done", created_at="2026-10-19T08:04:00Z",
        ),
        Document(
            id="doc-004", batch_id="batch-002", name="rates_oct.csv", type="csv",
            file_url="/files/doc-004", status="done", created_at="2026-10-18T14:01:00Z",
        ),
        Document(
            id="doc-005", batch_id="batch-003", name="annual_report.pdf", type="pdf",
            file_url="/files/doc-005", page_count=88, status="processing",
            created_at="2026-10-20T10:01:00Z",
        ),
    ]


def _batches() -> list[Batch]:
    return [
        Batch(
            id="batch-003",
            name="Finance Disclosures",
            pack_id="mining-v1",
            pack_name="Mining v1",
            files=[
                BatchFile(
                    id="f5", name="annual_report.pdf", type="PDF", size=3145728,
                    status="processing", progress=62, document_id="doc-005",
                )
            ],
            stage="mapping",
            status="running",
            created_at="2026-10-20T10:00:00Z",
            updated_at="2026-10-20T10:22:00Z",
            stats=BatchStats(
                total_files=1, total_fields=0, auto_approved=0, needs_review=0, missing=0
            ),
        ),
        Batch(
            id="batch-001",
            name="Q3 Production Reports",
            pack_id="mining-v1",
            pack_name="Mining v1",
            files=[
                BatchFile(
                    id="f1", name="rates_q3.xlsx", type="Excel", size=204800, status="done",
                    progress=100, document_id="doc-001",
                ),
                BatchFile(
                    id="f2", name="filing.pdf", type="PDF (scan)", size=1048576, status="done",
                    progress=100, document_id="doc-002",
                ),
                BatchFile(
                    id="f3", name="notes.html", type="HTML", size=51200, status="done",
                    progress=100, document_id="doc-003",
                ),
            ],
            stage="ready",
            status="done",
            created_at="2026-10-19T08:00:00Z",
            updated_at="2026-10-19T09:32:00Z",
            stats=BatchStats(
                total_files=3, total_fields=8, auto_approved=4, needs_review=3, missing=1
            ),
        ),
        Batch(
            id="batch-002",
            name="October Tariff Tables",
            pack_id="shipping-v1",
            pack_name="Shipping v1",
            files=[
                BatchFile(
                    id="f4", name="rates_oct.csv", type="CSV", size=102400, status="done",
                    progress=100, document_id="doc-004",
                )
            ],
            stage="ready",
            status="done",
            created_at="2026-10-18T14:00:00Z",
            updated_at="2026-10-18T14:45:00Z",
            stats=BatchStats(
                total_files=1, total_fields=2, auto_approved=2, needs_review=0, missing=0
            ),
        ),
    ]


def _mappings() -> list[Mapping]:
    return [
        Mapping(
            id="m1", document_id="doc-001", source_label="Nickel production",
            target_field="production_t", raw_value="12,500", raw_unit="lb", value="5.67",
            unit="t", confidence=0.96, status="auto",
            validations=[
                ValidationResult(name="Non-negative production", ok=True, message="Passes")
            ],
            conversion=Conversion(
                factor=0.000453592, rule_id="lb-t",
                formula_text="12,500 lb x 0.000453592 = 5.67 t",
            ),
            source_location=SourceLocationPdf(page=3, bbox=(0.1, 0.22, 0.5, 0.04)),
        ),
        Mapping(
            id="m2", document_id="doc-001", source_label="Cash cost",
            target_field="unit_cost", raw_value="$4.2", raw_unit="$/lb", value="9259",
            unit="$/t", confidence=0.61, status="review",
            reason="Footnote conflict: value may exclude royalties. Verify before accepting.",
            validations=[
                ValidationResult(name="Non-negative cost", ok=True, message="Passes"),
                ValidationResult(
                    name="Reasonable cost", ok=True, message="Within expected range"
                ),
            ],
            conversion=Conversion(
                factor=2204.62, rule_id="usd-lb-usd-t",
                formula_text="$4.2/lb x 2204.62 lb/t = $9,259/t",
            ),
            source_location=SourceLocationPdf(page=3, bbox=(0.1, 0.30, 0.55, 0.04)),
        ),
        Mapping(
            id="m3", document_id="doc-001", source_label="Mine name",
            target_field="site_name", raw_value="North Pit", value="North Pit",
            confidence=0.94, status="auto",
            validations=[
                ValidationResult(name="Required field present", ok=True, message="Passes")
            ],
            source_location=SourceLocationSheet(sheet="Summary", cell="B12"),
        ),
        Mapping(
            id="m4", document_id="doc-001", source_label="Not found",
            target_field="period", raw_value="", value="", confidence=0.0, status="missing",
            reason="Reporting period not found in document. Enter manually.",
            validations=[
                ValidationResult(
                    name="Required field present", ok=False, message="Missing required field"
                )
            ],
            source_location=SourceLocationText(start=0, end=0),
        ),
        Mapping(
            id="m5", document_id="doc-002", source_label="Production output",
            target_field="production_t", raw_value="8,200", raw_unit="lb", value="3.72",
            unit="t", confidence=0.88, status="review",
            reason="Low OCR confidence on source page. Verify value.",
            validations=[
                ValidationResult(name="Non-negative production", ok=True, message="Passes")
            ],
            conversion=Conversion(
                factor=0.000453592, rule_id="lb-t",
                formula_text="8,200 lb x 0.000453592 = 3.72 t",
            ),
            source_location=SourceLocationPdf(page=2, bbox=(0.2, 0.45, 0.4, 0.04)),
        ),
        Mapping(
            id="m6", document_id="doc-002", source_label="Site",
            target_field="site_name", raw_value="South Shaft", value="South Shaft",
            confidence=0.91, status="auto",
            validations=[
                ValidationResult(name="Required field present", ok=True, message="Passes")
            ],
            source_location=SourceLocationPdf(page=1, bbox=(0.1, 0.10, 0.4, 0.04)),
        ),
        Mapping(
            id="m7", document_id="doc-003", source_label="Operation",
            target_field="site_name", raw_value="East Basin", value="East Basin",
            confidence=0.93, status="auto",
            validations=[
                ValidationResult(name="Required field present", ok=True, message="Passes")
            ],
            source_location=SourceLocationText(start=412, end=422),
        ),
        Mapping(
            id="m8", document_id="doc-003", source_label="Reported output",
            target_field="production_t", raw_value="26,700", raw_unit="lb", value="12.11",
            unit="t", confidence=0.72, status="review",
            reason="Narrative disclosure, not a table. Verify the figure is the period total.",
            validations=[
                ValidationResult(name="Non-negative production", ok=True, message="Passes")
            ],
            conversion=Conversion(
                factor=0.000453592, rule_id="lb-t",
                formula_text="26,700 lb x 0.000453592 = 12.11 t",
            ),
            source_location=SourceLocationText(start=980, end=996),
        ),
        Mapping(
            id="m9", document_id="doc-004", source_label="Tariff",
            target_field="freight_rate", raw_value="2,450", raw_unit="$/TEU", value="2450",
            unit="$/TEU", confidence=0.97, status="auto",
            validations=[ValidationResult(name="Non-negative rate", ok=True, message="Passes")],
            source_location=SourceLocationSheet(sheet="Sheet1", cell="D4"),
        ),
        Mapping(
            id="m10", document_id="doc-004", source_label="POL",
            target_field="origin_port", raw_value="Jebel Ali", value="Jebel Ali",
            confidence=0.95, status="auto",
            validations=[
                ValidationResult(name="Required field present", ok=True, message="Passes")
            ],
            source_location=SourceLocationSheet(sheet="Sheet1", cell="A4"),
        ),
    ]


def _seed_events(batch_id: str) -> list[AgentEvent]:
    """The activity a finished batch would have produced. Same shape as a live run."""
    steps: list[tuple[str, str, Literal["running", "done", "error"], str]] = [
        ("Ingestion", "ingest", "done", "Read uploaded files"),
        ("Extractor", "parse", "done", "Extracted facts with page and bbox"),
        ("Mapper", "map", "done", "Proposed target fields from pack synonyms"),
        ("Resolver", "normalize", "done", "Applied declared conversion factors"),
        ("Verifier", "validate", "done", "Checked each value against its source snippet"),
    ]
    return [new_event(a, s, st, m) for a, s, st, m in steps]


_INSIGHTS = Insights(
    mapping_accuracy=0.91,
    conversion_correctness=0.96,
    manual_effort_saved=0.73,
    feedback_improvement=0.08,
    runs=[
        InsightRun(
            run_id="r1", date="2026-10-10", mapping_accuracy=0.78,
            conversion_correctness=0.88, manual_effort_saved=0.60, feedback_improvement=0.0,
        ),
        InsightRun(
            run_id="r2", date="2026-10-13", mapping_accuracy=0.83,
            conversion_correctness=0.91, manual_effort_saved=0.65, feedback_improvement=0.05,
        ),
        InsightRun(
            run_id="r3", date="2026-10-16", mapping_accuracy=0.87,
            conversion_correctness=0.93, manual_effort_saved=0.69, feedback_improvement=0.06,
        ),
        InsightRun(
            run_id="r4", date="2026-10-19", mapping_accuracy=0.91,
            conversion_correctness=0.96, manual_effort_saved=0.73, feedback_improvement=0.08,
        ),
    ],
    learned_corrections=[],
)


# --- The service --------------------------------------------------------------


class FixtureService:
    """Satisfies `deps.PipelineService` by reading and writing the real Repository.

    The fixture is seeded once into storage, not held in a dict, so every route exercises
    the same code path the engine will: a correction made through the API survives a
    reload, and the SqliteRepository is under test rather than mocked out.
    """

    def __init__(self, repository: Repository, event_log: EventLog) -> None:
        self._repo = repository
        self._log = event_log
        self._packs: dict[str, SchemaPack] = {p.id: p for p in _packs()}
        self._seeded: set[str] = set()

    # -- seeding ---------------------------------------------------------------

    def _ensure_seeded(self, tenant_id: str) -> None:
        if tenant_id in self._seeded:
            return
        self._seeded.add(tenant_id)
        try:
            if self._repo.list_batches(tenant_id=tenant_id):
                return
            for batch in _batches():
                self._repo.upsert_batch(batch, tenant_id=tenant_id)
                for event in _seed_events(batch.id):
                    self._log.emit(batch.id, event, tenant_id=tenant_id)
            for document in _documents():
                self._repo.upsert_document(document, tenant_id=tenant_id)
            for mapping in _mappings():
                self._repo.upsert_mapping(mapping, tenant_id=tenant_id)
        except Exception:
            # Containment: an unseedable store yields empty pages, not a dead app.
            pass

    def _document_names(self, tenant_id: str) -> dict[str, str]:
        names: dict[str, str] = {}
        for batch in self._repo.list_batches(tenant_id=tenant_id):
            for doc in self._repo.list_documents(batch.id, tenant_id=tenant_id):
                names[doc.id] = doc.name
        return names

    # -- home / insights -------------------------------------------------------

    def home_stats(self, *, tenant_id: str = DEFAULT_TENANT) -> HomeStats:
        self._ensure_seeded(tenant_id)
        batches = self._repo.list_batches(tenant_id=tenant_id)
        mappings = self._repo.list_mappings(tenant_id=tenant_id)
        documents = sum(len(b.files) for b in batches)
        settled = [m for m in mappings if m.status in ("auto", "approved")]
        open_rows = [m for m in mappings if m.status in OPEN_STATUSES]
        total = len(mappings) or 1
        return HomeStats(
            documents_processed=documents,
            auto_approved_pct=round(len(settled) / total, 4),
            fields_needing_review=len(open_rows),
            mapping_accuracy=_INSIGHTS.mapping_accuracy,
            mapping_accuracy_delta=_INSIGHTS.feedback_improvement,
            recent_batches=batches[:5],
        )

    def insights(self, *, tenant_id: str = DEFAULT_TENANT) -> Insights:
        self._ensure_seeded(tenant_id)
        names = self._document_names(tenant_id)
        corrections = [
            LearnedCorrection(
                id=fb.id,
                field=fb.to_field or fb.from_field or fb.source_label,
                from_value=fb.from_value or "",
                to_value=fb.to_value or "",
                document_name=names.get(fb.document_id, fb.document_id),
                learned_at=fb.created_at,
            )
            for fb in self._repo.list_feedback(tenant_id=tenant_id, limit=20)
        ]
        return _INSIGHTS.model_copy(update={"learned_corrections": corrections})

    # -- batches ---------------------------------------------------------------

    def list_batches(self, *, tenant_id: str = DEFAULT_TENANT) -> list[Batch]:
        self._ensure_seeded(tenant_id)
        return self._repo.list_batches(tenant_id=tenant_id)

    def create_batch(
        self,
        payload: CreateBatchPayload,
        files: Sequence[UploadedFile],
        *,
        tenant_id: str = DEFAULT_TENANT,
    ) -> Batch:
        self._ensure_seeded(tenant_id)
        now = _now()
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        pack = self._packs.get(payload.pack_id)
        batch_files = [
            BatchFile(
                id=f"{batch_id}-f{i}",
                name=f.name,
                type=f.media_type,
                size=f.size_bytes,
                status="ready",
                progress=0,
                document_id=None,
            )
            for i, f in enumerate(files)
        ]
        batch = Batch(
            id=batch_id,
            name=f"Upload {now[:19]}",
            pack_id=payload.pack_id,
            pack_name=pack.name if pack else payload.pack_id,
            files=batch_files,
            # `uploading`/`pending`, not `ready`: this service does not process. Saying
            # otherwise would make a fixture look like a finished run.
            stage="uploading",
            status="pending",
            created_at=now,
            updated_at=now,
            stats=BatchStats(
                total_files=len(batch_files), total_fields=0, auto_approved=0,
                needs_review=0, missing=0,
            ),
        )
        try:
            self._repo.upsert_batch(batch, tenant_id=tenant_id)
            self._log.emit(
                batch_id,
                new_event(
                    "Ingestion", "ingest", "running",
                    f"Accepted {len(batch_files)} file(s) for pack {payload.pack_id}",
                ),
                tenant_id=tenant_id,
            )
            if payload.url:
                self._log.emit(
                    batch_id,
                    new_event("Ingestion", "ingest", "running", f"Queued source URL {payload.url}"),
                    tenant_id=tenant_id,
                )
            self._log.emit(
                batch_id,
                new_event(
                    "Pipeline", "ingest", "error",
                    "No pipeline is wired (PIPELINE=fixture). The batch is stored, not processed.",
                ),
                tenant_id=tenant_id,
            )
        except Exception:
            pass
        return batch

    def get_batch(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Batch | None:
        self._ensure_seeded(tenant_id)
        return self._repo.get_batch(batch_id, tenant_id=tenant_id)

    def cancel_batch(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Batch | None:
        self._ensure_seeded(tenant_id)
        batch = self._repo.get_batch(batch_id, tenant_id=tenant_id)
        if batch is None:
            return None
        if batch.status in ("done", "failed", "cancelled"):
            # Cancelling a finished batch is a no-op, not an error: the UI may double-click.
            return batch
        cancelled = batch.model_copy(update={"status": "cancelled", "updated_at": _now()})
        self._repo.upsert_batch(cancelled, tenant_id=tenant_id)
        self._log.emit(
            batch_id,
            new_event("Pipeline", "cancel", "done", "Cancelled by the operator"),
            tenant_id=tenant_id,
        )
        return cancelled

    def batch_events(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> list[AgentEvent] | None:
        self._ensure_seeded(tenant_id)
        if self._repo.get_batch(batch_id, tenant_id=tenant_id) is None:
            return None
        return self._log.read(batch_id, tenant_id=tenant_id, after_seq=after_seq)

    # -- records and export ----------------------------------------------------

    def _records_for(self, batch_id: str, tenant_id: str) -> list[DatasetRecord]:
        """One row per document, built from that document's mappings.

        Derived rather than stored, so a correction made in the review drawer shows up in
        the dataset table on the next request without a second write path.
        """
        documents = self._repo.list_documents(batch_id, tenant_id=tenant_id)
        rows: list[DatasetRecord] = []
        for index, doc in enumerate(documents, start=1):
            mappings = self._repo.list_mappings(tenant_id=tenant_id, document_id=doc.id)
            if not mappings:
                continue
            fields: dict[str, Any] = {}
            page: int | None = None
            cell: str | None = None
            for m in mappings:
                fields[m.target_field] = None if m.status == "missing" else m.value
                loc = m.source_location
                if page is None and isinstance(loc, SourceLocationPdf):
                    page = loc.page
                if cell is None and isinstance(loc, SourceLocationSheet):
                    cell = loc.cell
            # The row's status is the worst lane in it: a row with one unreviewed field is
            # not an approved row. Law V -- three states, and the middle one is visible.
            statuses = {m.status for m in mappings}
            if "missing" in statuses:
                row_status = "missing"
            elif "review" in statuses:
                row_status = "review"
            elif "rejected" in statuses:
                row_status = "rejected"
            elif statuses == {"approved"}:
                row_status = "approved"
            else:
                row_status = "auto"
            rows.append(
                DatasetRecord(
                    id=f"rec-{index}",
                    document_id=doc.id,
                    document_name=doc.name,
                    _status=row_status,
                    _source_page=page,
                    _source_cell=cell,
                    **fields,
                )
            )
        return rows

    def batch_records(
        self,
        batch_id: str,
        *,
        page: int = 1,
        per_page: int = 50,
        tenant_id: str = DEFAULT_TENANT,
    ) -> PaginatedResponse[DatasetRecord] | None:
        self._ensure_seeded(tenant_id)
        if self._repo.get_batch(batch_id, tenant_id=tenant_id) is None:
            return None
        rows = self._records_for(batch_id, tenant_id)
        start = (page - 1) * per_page
        return PaginatedResponse[DatasetRecord](
            data=rows[start : start + per_page],
            total=len(rows),
            page=page,
            per_page=per_page,
        )

    def export_batch(
        self,
        batch_id: str,
        *,
        fmt: Literal["csv", "json"],
        audit: bool = False,
        tenant_id: str = DEFAULT_TENANT,
    ) -> ExportFile | None:
        self._ensure_seeded(tenant_id)
        if self._repo.get_batch(batch_id, tenant_id=tenant_id) is None:
            return None
        rows = [r.model_dump(by_alias=True) for r in self._records_for(batch_id, tenant_id)]
        if fmt == "json":
            payload = json.dumps(rows, indent=2, sort_keys=True, default=str).encode("utf-8")
            return ExportFile(
                filename=f"{batch_id}.json", media_type="application/json", content=payload
            )

        fixed = ["id", "document_id", "document_name"]
        dynamic = sorted({k for r in rows for k in r if not k.startswith("_") and k not in fixed})
        columns = [*fixed, *dynamic, "_status"]
        if audit:
            columns += ["_source_page", "_source_cell"]
        buffer = io.StringIO(newline="")
        # lineterminator is pinned: the platform default would make the same data render
        # to different bytes on Windows and Linux, and Law IV says byte-identical.
        writer = csv.DictWriter(
            buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({c: "" if row.get(c) is None else row.get(c) for c in columns})
        return ExportFile(
            filename=f"{batch_id}.csv", media_type="text/csv", content=buffer.getvalue().encode()
        )

    # -- documents -------------------------------------------------------------

    def get_document(
        self, document_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> Document | None:
        self._ensure_seeded(tenant_id)
        return self._repo.get_document(document_id, tenant_id=tenant_id)

    def document_mappings(
        self, document_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> list[Mapping] | None:
        self._ensure_seeded(tenant_id)
        if self._repo.get_document(document_id, tenant_id=tenant_id) is None:
            return None
        return self._repo.list_mappings(tenant_id=tenant_id, document_id=document_id)

    # -- mappings --------------------------------------------------------------

    @staticmethod
    def _approve(mapping: Mapping, status: str) -> tuple[Mapping, str | None]:
        """Set a status that asserts a value, refusing when there is no provenance.

        `contracts.Mapping` makes an approved row without a source_location impossible to
        construct. Rather than let that surface as a 500, the mapping stays in the review
        lane and says why -- which is the honest answer, not a workaround.
        """
        if status in ("auto", "approved") and mapping.source_location is None:
            return (
                mapping.model_copy(
                    update={
                        "status": "review",
                        "reason": "Cannot approve a value with no source location.",
                    }
                ),
                "Not approved: this value has no provenance, so it cannot be accepted.",
            )
        return mapping.model_copy(update={"status": status}), None

    def patch_mapping(
        self,
        mapping_id: str,
        payload: MappingPatchPayload,
        *,
        tenant_id: str = DEFAULT_TENANT,
    ) -> MappingPatchResponse | None:
        self._ensure_seeded(tenant_id)
        before = self._repo.get_mapping(mapping_id, tenant_id=tenant_id)
        if before is None:
            return None

        refusal: str | None = None
        if payload.action == "reject":
            after = before.model_copy(update={"status": "rejected"})
        elif payload.action == "accept":
            after, refusal = self._approve(before, "approved")
        else:  # edit
            update: dict[str, Any] = {}
            if payload.value is not None:
                update["value"] = payload.value
            if payload.unit is not None:
                update["unit"] = payload.unit
            edited = before.model_copy(update=update)
            # An analyst who typed the value has reviewed it; leaving it in `review` would
            # ask them to review their own correction.
            after, refusal = self._approve(edited, "approved")
        if payload.reason:
            after = after.model_copy(update={"reason": payload.reason})

        # A precedent is written when the analyst settled a field the pipeline could not:
        # a stated rule, not a coin flip, so the demo says the same thing twice.
        learned = refusal is None and payload.action in ("accept", "edit") and (
            before.status in OPEN_STATUSES
        )
        if learned:
            message = (
                f'Learned: "{before.source_label}" resolves to "{after.target_field}" '
                "for this tenant. The next run resolves it with no model call."
            )
        elif refusal is not None:
            message = refusal
        elif payload.action == "reject":
            message = "Rejected. No precedent written: a rejection is not a mapping."
        else:
            message = "No precedent written: this field was already settled."

        try:
            self._repo.upsert_mapping(after, tenant_id=tenant_id)
            self._repo.append_feedback(
                FeedbackEvent(
                    id=f"fb-{uuid.uuid4().hex[:12]}",
                    tenant_id=tenant_id,
                    mapping_id=before.id,
                    document_id=before.document_id,
                    source_label=before.source_label,
                    action=payload.action,
                    from_field=before.target_field,
                    to_field=after.target_field,
                    from_value=before.value,
                    to_value=after.value,
                    reason=payload.reason,
                ),
                tenant_id=tenant_id,
            )
        except Exception:
            pass
        return MappingPatchResponse(mapping=after, learned=learned, learned_message=message)

    def bulk_accept(
        self, payload: BulkAcceptPayload, *, tenant_id: str = DEFAULT_TENANT
    ) -> BulkAcceptResponse | None:
        self._ensure_seeded(tenant_id)
        if self._repo.get_document(payload.document_id, tenant_id=tenant_id) is None:
            return None
        accepted: list[Mapping] = []
        for mapping in self._repo.list_mappings(
            tenant_id=tenant_id, document_id=payload.document_id
        ):
            if mapping.confidence < payload.min_confidence:
                continue
            # `review` only, never `missing`. A missing field has no value to accept, and
            # min_confidence=0 would otherwise sweep the whole third lane into `approved`
            # -- which is exactly the silent error the gate exists to prevent.
            if mapping.status != "review":
                continue
            after, refusal = self._approve(mapping, "approved")
            if refusal is not None:
                continue
            try:
                self._repo.upsert_mapping(after, tenant_id=tenant_id)
            except Exception:
                continue
            accepted.append(after)
        return BulkAcceptResponse(accepted_count=len(accepted), mappings=accepted)

    def review_queue(self, *, tenant_id: str = DEFAULT_TENANT) -> list[ReviewQueueItem]:
        self._ensure_seeded(tenant_id)
        names = self._document_names(tenant_id)
        batch_of: dict[str, str] = {}
        for batch in self._repo.list_batches(tenant_id=tenant_id):
            for doc in self._repo.list_documents(batch.id, tenant_id=tenant_id):
                batch_of[doc.id] = batch.id
        return [
            ReviewQueueItem(
                mapping_id=m.id,
                document_id=m.document_id,
                document_name=names.get(m.document_id, m.document_id),
                batch_id=batch_of.get(m.document_id, ""),
                source_label=m.source_label,
                target_field=m.target_field,
                reason=m.reason,
                confidence=m.confidence,
                status=m.status,
            )
            for m in self._repo.list_mappings(tenant_id=tenant_id, statuses=OPEN_STATUSES)
        ]

    # -- packs -----------------------------------------------------------------

    def list_packs(self, *, tenant_id: str = DEFAULT_TENANT) -> list[SchemaPack]:
        return list(self._packs.values())

    def get_pack(self, pack_id: str, *, tenant_id: str = DEFAULT_TENANT) -> SchemaPack | None:
        return self._packs.get(pack_id)

    def put_pack(
        self, pack_id: str, patch: dict[str, Any], *, tenant_id: str = DEFAULT_TENANT
    ) -> SchemaPack | None:
        current = self._packs.get(pack_id)
        if current is None:
            return None
        merged = {**current.model_dump(), **{k: v for k, v in patch.items() if k != "id"}}
        merged["id"] = pack_id
        merged["updated_at"] = _now()
        try:
            updated = SchemaPack.model_validate(merged)
        except Exception:
            # A malformed edit leaves the pack as it was. Law III: we never author one.
            return current
        self._packs[pack_id] = updated
        return updated

    # -- health ----------------------------------------------------------------

    def health_layers(self, *, tenant_id: str = DEFAULT_TENANT) -> list[HealthLayer]:
        reachable, detail = self._repo.ping()
        return [
            HealthLayer(
                name="Storage",
                status="ok" if reachable else "down",
                message=f"{detail} | source=env:REPOSITORY",
            ),
            HealthLayer(
                name="Pipeline",
                status="degraded",
                message=(
                    "fixture service: the engine is not wired, so no document is processed "
                    "| source=env:PIPELINE"
                ),
            ),
        ]
