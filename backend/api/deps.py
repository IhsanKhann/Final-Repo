"""The seam between the API and the pipeline, plus the app's dependency wiring.

Exists because the API had to be serveable before the engine existed. `PipelineService` is
the entire list of things a route needs from the backbone -- nothing more, so the engine
can satisfy it without agreeing to anything else -- and `FixtureService` satisfies it today
so the routes are testable and the frontend runs now. The real engine is wired in by
`use_pipeline_service(...)`: one call, no route changes.

What this module refuses to do:
  * It refuses to import `backend.engine.units/resolve/gate/ledger` or `backend.memory`.
    They are being written in parallel and may not exist. The real service is imported
    lazily, inside a function, only when PIPELINE says so, and an ImportError degrades to
    the fixture instead of refusing to boot.
  * It refuses to let FastAPI types reach the engine. An upload crosses the seam as
    `UploadedFile` (bytes and a name), and a download comes back as `ExportFile`, so the
    engine never imports a web framework and can be driven from a test or a CLI.
  * It refuses to signal absence by raising. A getter returns `None` for "no such row";
    the route turns that into a typed 404. No layer raises across its seam (CLAUDE.md 6).
  * It refuses to invent a tenant. `tenant_id` is a keyword on every method, defaulted to
    "demo", so adding auth later is one middleware (CLAUDE.md 6b).
"""

from __future__ import annotations

import os
from typing import Any, Literal, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict

from backend.api.eventlog import EventLog, RepositoryEventLog
from backend.api.repository import Repository, make_repository
from backend.engine.config import DEFAULT_TENANT, ConfigStore, make_store
from backend.engine.contracts import (
    AgentEvent,
    Batch,
    BulkAcceptPayload,
    BulkAcceptResponse,
    CreateBatchPayload,
    DatasetRecord,
    Document,
    HealthLayer,
    HomeStats,
    Insights,
    Mapping,
    MappingPatchPayload,
    MappingPatchResponse,
    PaginatedResponse,
    ReviewQueueItem,
    SchemaPack,
)

__all__ = [
    "UploadedFile",
    "ExportFile",
    "Problem",
    "ApiProblem",
    "PipelineService",
    "use_pipeline_service",
    "get_pipeline_service",
    "get_repository",
    "get_event_log",
    "get_config_store",
    "get_tenant_id",
    "reset_wiring",
]


# --- Values that cross the seam in place of framework objects -----------------


class UploadedFile(BaseModel):
    """An upload, already read, with no FastAPI in it.

    The route does the reading; the engine gets bytes. That is what lets the same
    `create_batch` call be driven from a test, a CLI or an Eventarc handler later.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    media_type: str = "application/octet-stream"
    size_bytes: int = 0
    content: bytes = b""


class ExportFile(BaseModel):
    """A rendered download. Bytes, because Law IV says the export is a render.

    `content` is produced once, deterministically, by the service. The route only attaches
    headers, so there is nowhere for a non-deterministic byte to enter.
    """

    model_config = ConfigDict(extra="forbid")

    filename: str
    media_type: str
    content: bytes


class Problem(BaseModel):
    """The typed error body. Every non-2xx response from this API is one of these.

    `detail` is first and plainly named because the frontend's ApiError reads the response
    body as text and shows it; the machine-readable parts sit beside it.
    """

    model_config = ConfigDict(extra="forbid")

    detail: str
    code: str
    resource: str | None = None
    id: str | None = None


class ApiProblem(Exception):
    """Raised only inside the API layer and converted by one handler in main.py.

    This is not a layer raising across a seam: it never leaves the API, and the service
    seam below it signals absence with `None`, not with exceptions.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        code: str,
        resource: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.problem = Problem(detail=detail, code=code, resource=resource, id=id)

    @classmethod
    def not_found(cls, resource: str, id: str) -> ApiProblem:
        return cls(404, f"{resource} {id!r} not found", code="not_found", resource=resource, id=id)


# --- The narrow Protocol the engine implements --------------------------------


@runtime_checkable
class PipelineService(Protocol):
    """Everything the twelve endpoints need from the backbone. Nothing else.

    Conventions, which are the contract as much as the signatures are:
      * `None` from a single-item getter means "no such thing" and becomes a typed 404.
        It never means "failed".
      * A list getter returns `[]`, never `None`, unless its parent is missing -- then
        `None`, so the route can tell an empty document from an absent one.
      * No method raises. A provider outage is reported through `health_layers()` and
        through `Mapping.status` / `reason`, per CLAUDE.md 6.
      * `tenant_id` is keyword-only with a default on every method.
    """

    # home / insights
    def home_stats(self, *, tenant_id: str = DEFAULT_TENANT) -> HomeStats: ...

    def insights(self, *, tenant_id: str = DEFAULT_TENANT) -> Insights: ...

    # batches
    def list_batches(self, *, tenant_id: str = DEFAULT_TENANT) -> list[Batch]: ...

    def create_batch(
        self,
        payload: CreateBatchPayload,
        files: Sequence[UploadedFile],
        *,
        tenant_id: str = DEFAULT_TENANT,
    ) -> Batch:
        """Accept an upload and return the batch immediately, before processing.

        One batch, many files -- but the pipeline entry point underneath takes ONE
        document, so fan-out stays a wrapper (CLAUDE.md 6b).
        """

    def get_batch(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Batch | None: ...

    def cancel_batch(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Batch | None: ...

    def batch_events(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> list[AgentEvent] | None:
        """Agent activity for a batch, oldest first. `None` only if the batch is absent.

        `after_seq` is the SSE resume cursor; the MVP poller passes 0.
        """

    def batch_records(
        self,
        batch_id: str,
        *,
        page: int = 1,
        per_page: int = 50,
        tenant_id: str = DEFAULT_TENANT,
    ) -> PaginatedResponse[DatasetRecord] | None:
        """One page of the gold table. `total` is the unpaged count, not len(data)."""

    def export_batch(
        self,
        batch_id: str,
        *,
        fmt: Literal["csv", "json"],
        audit: bool = False,
        tenant_id: str = DEFAULT_TENANT,
    ) -> ExportFile | None:
        """Render the batch. Same data in -> byte-identical file out (Law IV).

        `audit` adds the provenance columns; it never changes the values.
        """

    # documents
    def get_document(
        self, document_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> Document | None: ...

    def document_mappings(
        self, document_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> list[Mapping] | None: ...

    # mappings
    def patch_mapping(
        self,
        mapping_id: str,
        payload: MappingPatchPayload,
        *,
        tenant_id: str = DEFAULT_TENANT,
    ) -> MappingPatchResponse | None:
        """Apply an analyst correction and report whether a precedent was written.

        `learned` / `learned_message` are the feedback loop surfacing in the UI; returning
        `learned=False` is a legitimate answer and must not be faked.
        """

    def bulk_accept(
        self, payload: BulkAcceptPayload, *, tenant_id: str = DEFAULT_TENANT
    ) -> BulkAcceptResponse | None:
        """Accept every `review` field at or above `min_confidence`. `None` if no document.

        `review` only -- never `missing`. A missing field has no value to accept, and
        `min_confidence=0` would otherwise sweep the whole third lane into `approved`,
        which is the silent error the gate exists to prevent.
        """

    def review_queue(self, *, tenant_id: str = DEFAULT_TENANT) -> list[ReviewQueueItem]: ...

    # packs
    def list_packs(self, *, tenant_id: str = DEFAULT_TENANT) -> list[SchemaPack]: ...

    def get_pack(self, pack_id: str, *, tenant_id: str = DEFAULT_TENANT) -> SchemaPack | None: ...

    def put_pack(
        self, pack_id: str, patch: dict[str, Any], *, tenant_id: str = DEFAULT_TENANT
    ) -> SchemaPack | None:
        """Apply a partial update to a pack. A drafted declaration is born PROPOSED.

        `patch` is the frontend's `Partial<SchemaPack>`: absent keys are untouched.
        """

    # health
    def health_layers(self, *, tenant_id: str = DEFAULT_TENANT) -> list[HealthLayer]:
        """The layers only the pipeline can speak for (pack loaded, engine ready, memory).

        Key presence and provenance are NOT in here: /api/health reads those from
        config.py directly, so a service cannot misreport whether a key exists.
        """


# --- Wiring -------------------------------------------------------------------
# Module-level singletons, deliberately: a Repository is a file path and a ConfigStore is
# a file path, and both open a connection per call, so there is nothing here to go stale.


_service: PipelineService | None = None
_repository: Repository | None = None
_event_log: EventLog | None = None
_store: ConfigStore | None = None


def use_pipeline_service(service: PipelineService) -> None:
    """Wire the real engine in. This is the whole handover: one call, no route changes."""
    global _service
    _service = service


def reset_wiring() -> None:
    """Drop the singletons. For tests that repoint API_DB_PATH / CONFIG_DB_PATH."""
    global _service, _repository, _event_log, _store
    _service = None
    _repository = None
    _event_log = None
    _store = None


def get_repository() -> Repository:
    global _repository
    if _repository is None:
        _repository = make_repository()
    return _repository


def get_event_log() -> EventLog:
    global _event_log
    if _event_log is None:
        _event_log = RepositoryEventLog(get_repository())
    return _event_log


def get_config_store() -> ConfigStore:
    global _store
    if _store is None:
        _store = make_store()
    return _store


#: Where the real service is expected to live when PIPELINE=engine, as "module:factory".
#: Overridable by PIPELINE_SERVICE so wiring the engine in costs one env var and not an
#: edit to this file -- the same shape as REPOSITORY and CONFIG_STORE.
DEFAULT_SERVICE_FACTORY = "backend.service:build_service"


def _build_default_service() -> PipelineService:
    """PIPELINE=engine asks for the real thing; anything else, or a failure, is fixture.

    The import is by name, inside the function, because the engine is being written in
    parallel and `backend/pipeline.py` is a composition root (`process_document`, one
    document at a time), not a PipelineService. The factory named here is the adapter
    between the two, and it is called with the repository, the event log and the config
    store so it does not have to find them for itself.

    A missing or broken factory degrades to the fixture rather than refusing to boot:
    README section 7 promises the backend starts and serves with nothing configured.
    """
    want = (os.environ.get("PIPELINE") or "persisted").strip().lower()
    if want == "engine":
        target = os.environ.get("PIPELINE_SERVICE") or DEFAULT_SERVICE_FACTORY
        try:
            from importlib import import_module

            module_name, _, attr = target.partition(":")
            factory = getattr(import_module(module_name), attr or "build_service")
            return factory(
                repository=get_repository(),
                event_log=get_event_log(),
                config_store=get_config_store(),
            )
        except Exception:
            pass

    # Fixtures are reachable, but never by default. The fixture seeds a plausible accuracy
    # figure and a pack nobody authored; serving those because a variable was left unset
    # means the demo performs live the exact failure this product claims to prevent -- a
    # confident number with nothing behind it. So the fixture now requires asking for it
    # by name, and the default below invents nothing.
    asked_for_fixtures = (os.environ.get("USE_FIXTURES") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ) or want == "fixture"
    if asked_for_fixtures:
        from backend.api.fixtures import FixtureService

        return FixtureService(repository=get_repository(), event_log=get_event_log())

    from backend.api.persisted import PersistedService

    return PersistedService(
        repository=get_repository(),
        event_log=get_event_log(),
        config_store=get_config_store(),
    )


def get_pipeline_service() -> PipelineService:
    global _service
    if _service is None:
        _service = _build_default_service()
    return _service


def get_tenant_id() -> str:
    """One function, so auth becomes one middleware that overrides it.

    Today every request is the demo tenant. Tomorrow a dependency override or a middleware
    puts the authenticated tenant here and not one route signature changes.
    """
    return os.environ.get("TENANT_ID") or DEFAULT_TENANT
