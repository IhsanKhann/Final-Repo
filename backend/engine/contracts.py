"""Pydantic v2 mirror of Frontend/src/api/types.ts. That file is law; this one conforms.

Exists so a boundary type is validated once, here, rather than trusted everywhere. What it
refuses to do: it refuses to let a value exist without provenance, and it refuses to
accept a field the frontend never declared (extra="forbid" on everything crossing the
seam, so a typo in a route handler fails loudly instead of shipping a silent null).

Vocabulary is the frontend's, including inside the engine: the third lane is `missing`,
never "refused"; bbox is normalized 0-1; confidence is a float 0-1, never a percentage.

One deliberate divergence from types.ts, flagged rather than hidden: `Mapping.
source_location` is required in TypeScript but Optional here, because a `missing` lane row
is precisely the case where no source location exists. The model_validator below makes it
mandatory for every status that carries a value (`auto`, `approved`), which is the
invariant the TypeScript type was reaching for.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Generic, Literal, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Core status vocabulary ---------------------------------------------------

MappingStatus = Literal["auto", "review", "missing", "approved", "rejected"]
BatchStage = Literal[
    "uploading", "ingesting", "parsing", "mapping", "normalizing", "validating", "ready", "failed"
]
BatchStatus = Literal["pending", "running", "done", "failed", "cancelled"]
FileStatus = Literal["ready", "uploading", "processing", "done", "error", "unsupported"]

#: The statuses that assert a value was actually read off a document. These require
#: provenance; the others describe the absence or the refusal of a value.
STATUSES_REQUIRING_PROVENANCE: frozenset[str] = frozenset({"auto", "approved"})


class Boundary(BaseModel):
    """Base for every type that crosses the API seam."""

    model_config = ConfigDict(extra="forbid")


# --- Source location ----------------------------------------------------------


class SourceLocationPdf(Boundary):
    type: Literal["pdf"] = "pdf"
    page: int = Field(ge=1)
    #: [x, y, w, h], NORMALIZED 0-1. The adapter divides by page width/height once.
    bbox: tuple[float, float, float, float]

    @field_validator("bbox")
    @classmethod
    def _normalized(cls, v: tuple[float, float, float, float]):
        for n in v:
            if not (0.0 <= n <= 1.0):
                raise ValueError(
                    f"bbox must be normalized 0-1, got {v!r}. Divide by page "
                    "width/height in the adapter, never in the UI."
                )
        return v


class SourceLocationSheet(Boundary):
    type: Literal["sheet"] = "sheet"
    sheet: str
    cell: str  # e.g. "B12"


class SourceLocationText(Boundary):
    type: Literal["text"] = "text"
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end < self.start:
            raise ValueError(f"text span end {self.end} precedes start {self.start}")
        return self


SourceLocation = Annotated[
    Union[SourceLocationPdf, SourceLocationSheet, SourceLocationText],
    Field(discriminator="type"),
]


# --- Validation and conversion ------------------------------------------------


class ValidationResult(Boundary):
    name: str
    ok: bool
    message: str


class Conversion(Boundary):
    factor: float
    rule_id: str
    #: Human-readable, shown in the UI: "x 12 (monthly -> annual)", not "factor=12".
    formula_text: str


# --- Mapping ------------------------------------------------------------------


class Mapping(Boundary):
    id: str
    document_id: str
    source_label: str
    target_field: str
    raw_value: str
    raw_unit: str | None = None
    value: str
    unit: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    status: MappingStatus
    reason: str | None = None
    conversion: Conversion | None = None
    validations: list[ValidationResult] = Field(default_factory=list)
    source_location: SourceLocation | None = None

    @model_validator(mode="after")
    def _provenance_required(self):
        if self.status in STATUSES_REQUIRING_PROVENANCE and self.source_location is None:
            raise ValueError("a value without provenance cannot be constructed")
        return self


# --- Batch / run --------------------------------------------------------------


class BatchFile(Boundary):
    id: str
    name: str
    type: str
    size: int
    status: FileStatus
    progress: int | None = Field(default=None, ge=0, le=100)
    document_id: str | None = None
    error: str | None = None


class BatchStats(Boundary):
    total_files: int
    total_fields: int
    auto_approved: int
    needs_review: int
    missing: int


class Batch(Boundary):
    id: str
    name: str
    pack_id: str
    pack_name: str
    files: list[BatchFile] = Field(default_factory=list)
    stage: BatchStage
    status: BatchStatus
    created_at: str
    updated_at: str
    stats: BatchStats | None = None


class AgentEvent(Boundary):
    """Written to an EventLog from day one so SSE is one endpoint, not a rewrite."""

    id: str
    agent: str
    step: str
    status: Literal["running", "done", "error"]
    message: str
    timestamp: str
    file_id: str | None = None


class Document(Boundary):
    id: str
    batch_id: str
    name: str
    type: Literal["pdf", "xlsx", "csv", "html", "txt"]
    file_url: str
    page_count: int | None = None
    status: FileStatus
    created_at: str


# --- Schema pack (the frontend's view of a pack) ------------------------------


class SchemaField(Boundary):
    name: str
    label: str
    type: Literal["number", "string", "date", "boolean"]
    unit: str | None = None
    required: bool
    synonyms: list[str] = Field(default_factory=list)


class UnitConversion(Boundary):
    id: str
    from_unit: str
    to_unit: str
    factor: float
    formula: str | None = None


class BusinessRule(Boundary):
    id: str
    name: str
    field: str
    condition: str
    action: Literal["flag", "reject", "warn"]
    description: str


class SchemaPack(Boundary):
    id: str
    name: str
    version: str
    description: str | None = None
    fields: list[SchemaField] = Field(default_factory=list)
    conversions: list[UnitConversion] = Field(default_factory=list)
    rules: list[BusinessRule] = Field(default_factory=list)
    updated_at: str


# --- Review queue -------------------------------------------------------------


class ReviewQueueItem(Boundary):
    mapping_id: str
    document_id: str
    document_name: str
    batch_id: str
    source_label: str
    target_field: str
    reason: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    status: MappingStatus


# --- Dataset record -----------------------------------------------------------


class DatasetRecord(BaseModel):
    """One row of the gold table.

    The only boundary type that permits extra keys, because types.ts declares an index
    signature: the mapped field names come from the customer's pack and so cannot be
    enumerated here without putting domain nouns in the engine (Law II). Serialize with
    by_alias=True so the underscore-prefixed keys reach the UI as declared.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    document_id: str
    document_name: str
    status: MappingStatus = Field(alias="_status", serialization_alias="_status")
    source_page: int | None = Field(
        default=None, alias="_source_page", serialization_alias="_source_page"
    )
    source_cell: str | None = Field(
        default=None, alias="_source_cell", serialization_alias="_source_cell"
    )


# --- Insights -----------------------------------------------------------------


class InsightRun(Boundary):
    run_id: str
    date: str
    mapping_accuracy: float
    conversion_correctness: float
    manual_effort_saved: float
    feedback_improvement: float


class LearnedCorrection(Boundary):
    id: str
    field: str
    from_value: str
    to_value: str
    document_name: str
    learned_at: str


class Insights(Boundary):
    mapping_accuracy: float
    conversion_correctness: float
    manual_effort_saved: float
    feedback_improvement: float
    runs: list[InsightRun] = Field(default_factory=list)
    learned_corrections: list[LearnedCorrection] = Field(default_factory=list)


# --- Health -------------------------------------------------------------------


class HealthLayer(Boundary):
    name: str
    status: Literal["ok", "degraded", "down"]
    latency_ms: int | None = None
    message: str | None = None


class HealthStatus(Boundary):
    overall: Literal["ok", "degraded", "down"]
    layers: list[HealthLayer] = Field(default_factory=list)
    checked_at: str


# --- API request / response shapes --------------------------------------------

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    data: list[T]
    total: int
    page: int
    per_page: int


class MappingPatchPayload(Boundary):
    action: Literal["accept", "reject", "edit"]
    value: str | None = None
    unit: str | None = None
    reason: str | None = None


class MappingPatchResponse(Boundary):
    """learned/learned_message are the feedback loop surfacing in the UI."""

    mapping: Mapping
    learned: bool | None = None
    learned_message: str | None = None


class BulkAcceptPayload(Boundary):
    document_id: str
    min_confidence: float = Field(ge=0.0, le=1.0)


class BulkAcceptResponse(Boundary):
    accepted_count: int
    mappings: list[Mapping] = Field(default_factory=list)


class CreateBatchPayload(Boundary):
    pack_id: str
    url: str | None = None


class HomeStats(Boundary):
    documents_processed: int
    auto_approved_pct: float
    fields_needing_review: int
    mapping_accuracy: float
    mapping_accuracy_delta: float
    recent_batches: list[Batch] = Field(default_factory=list)


# --- Internal types the frontend never sees -----------------------------------


class Authority(int, Enum):
    """Resolution authority order. Higher wins. resolve.py is the only consumer.

    A model proposal is the weakest thing in the system, below an analyst precedent and
    far below a rule the customer quoted from their own document. That ordering is the
    product's claim.
    """

    MODEL = 1
    ANALYST = 2
    PACK_AUTHORED = 3
    PACK_QUOTED = 4


class DocumentRecord(Boundary):
    """A document as the pipeline holds it, before anything is extracted."""

    id: str
    tenant_id: str = "demo"
    batch_id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    page_count: int | None = None
    status: FileStatus = "ready"
    error: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ExtractedFact(Boundary):
    """What an adapter or the extractor agent produces. No mapping decision in here.

    Every fact carries its source_location: this is the one place provenance enters the
    system, and nothing downstream may invent it.
    """

    document_id: str
    source_label: str
    raw_value: str
    raw_unit: str | None = None
    source_location: SourceLocation
    #: Which RECORD inside the document this fact belongs to. One source document can
    #: hold many records -- a spreadsheet holds one per row -- so a document is not a
    #: record. Set deterministically by the adapter, which is the only layer that knows
    #: the document's own structure (a sheet row number, an HTML table row index, a PDF
    #: table row).
    #:
    #: Empty means "this document is a single record", which is the honest degenerate case
    #: for a narrative disclosure. It is a default rather than a required field so that
    #: every existing fixture keeps constructing, and
    #: tests/test_a_document_can_hold_many_records.py asserts no real adapter leaves it
    #: empty -- an adapter that forgot would silently collapse 30 records into 1, which is
    #: the bug this field exists to fix.
    record_key: str = ""
    #: Any prior arriving from an upstream extractor, recorded as evidence, never trusted.
    extractor_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    context: str | None = None


class Proposal(Boundary):
    """The only thing the intelligence layer may return. It proposes; it never decides.

    target_field must be one of the candidates the deterministic retriever supplied -- the
    model may not name a field the pack does not declare. engine/resolve.py enforces that.
    """

    source_label: str
    target_field: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    model: str
    prompt_version: str
    authority: Authority = Authority.MODEL
    #: Whether a model was actually consulted to produce this. False when deterministic
    #: retrieval resolved the label on its own. The proposer is the only layer that knows,
    #: so it states it here rather than letting the engine infer it from the authority --
    #: an exact synonym match carries MODEL authority but consulted no model, and guessing
    #: from authority would overcount model calls in exactly the metric we claim to improve.
    used_model: bool = True


class Unavailable(Boundary):
    """Returned instead of a Proposal when intelligence cannot answer.

    This type is why a provider outage is a degraded banner instead of a failed run.
    It means the field goes to the review tray. It never means a guess.
    """

    reason: Literal[
        "no-key", "bad-key", "model-unavailable", "rate-limited", "timeout", "provider-down",
        "non-conforming-reply", "budget-exhausted",
    ]
    detail: str | None = None


ProposalOutcome = Union[Proposal, Unavailable]


class FeedbackEvent(Boundary):
    """One analyst correction. Append-only; this is the learning signal."""

    id: str
    tenant_id: str = "demo"
    mapping_id: str
    document_id: str
    source_label: str
    action: Literal["accept", "reject", "edit"]
    from_field: str | None = None
    to_field: str | None = None
    from_value: str | None = None
    to_value: str | None = None
    reason: str | None = None
    actor: str = "analyst"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Precedent(Boundary):
    """(tenant, source_label) -> canonical field, learned from an analyst correction.

    Ranks above a model proposal and below a QUOTED pack rule. A precedent hit resolves
    with no model call at all, which is what makes round 2 cheaper rather than just
    re-prompted.
    """

    tenant_id: str = "demo"
    source_label: str
    target_field: str
    authority: Authority = Authority.ANALYST
    times_applied: int = 0
    learned_from_mapping_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RoundReport(Boundary):
    """Round 1 vs 2 vs 3, with the controlled variables recorded.

    comparable is part of the report, not a nicety: if documents, pack version, model,
    temperature or prompt version differ between rounds, the comparison is void and the UI
    shows that instead of a number.
    """

    round: int
    tenant_id: str = "demo"
    pack_id: str
    pack_version: str
    #: Sixth controlled variable. A provider change moves what `sampling` can even mean,
    #: so two rounds on different providers are not comparable however identical the rest.
    provider: str
    model: str
    #: What was actually SENT, never what was intended: "temperature=0" for an
    #: openai-dialect provider, or "not-sent: removed by provider" for the anthropic
    #: dialect, where temperature/top_p/top_k are removed and any value is a 400.
    #: Printing "temperature 0" for a provider that cannot accept it would be a false
    #: claim about a controlled variable (CLAUDE.md 4).
    sampling: str
    prompt_version: str
    documents_fingerprint: str
    docs: int
    fields: int
    auto_accepted: int
    flagged: int
    missing: int
    mapping_accuracy: float
    conversion_correctness: float
    precedents_applied: int
    model_calls_skipped: int
    analyst_minutes_saved: float
    cost_usd: float
    comparable: bool = True
    not_comparable_reason: str | None = None
    delta_vs_previous: dict[str, float] | None = None


__all__ = [
    "MappingStatus", "BatchStage", "BatchStatus", "FileStatus",
    "STATUSES_REQUIRING_PROVENANCE",
    "SourceLocation", "SourceLocationPdf", "SourceLocationSheet", "SourceLocationText",
    "ValidationResult", "Conversion", "Mapping",
    "BatchFile", "BatchStats", "Batch", "AgentEvent", "Document",
    "SchemaField", "UnitConversion", "BusinessRule", "SchemaPack",
    "ReviewQueueItem", "DatasetRecord",
    "InsightRun", "LearnedCorrection", "Insights",
    "HealthLayer", "HealthStatus", "PaginatedResponse",
    "MappingPatchPayload", "MappingPatchResponse",
    "BulkAcceptPayload", "BulkAcceptResponse", "CreateBatchPayload", "HomeStats",
    "Authority", "DocumentRecord", "ExtractedFact", "Proposal", "Unavailable",
    "ProposalOutcome", "FeedbackEvent", "Precedent", "RoundReport",
]
