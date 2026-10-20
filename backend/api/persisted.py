"""The honest default service: serves what has actually happened, and invents nothing.

Exists because the alternative was shipping a fabricated accuracy figure to a screen. A
demo that shows `mapping_accuracy: 0.91` while no run has been scored is performing live
the exact failure this product claims to prevent -- a confident number with nothing behind
it. No measured accuracy exists until the golden set is confirmed, so this service reports
none, and says why through the health layers.

So the rule here is narrow and absolute: every number this service returns is counted from
rows in the repository, or it is zero with a reason. There is no literal metric anywhere in
this file.

It is also the service that makes `/api/packs` truthful: the pack list comes from the pack
loader reading `backend/packs/`, so the Schema page shows the rulebook that actually
governs a run rather than a decorative one.

It is also where the two decisions no layer below it is allowed to make are taken: which
PDF adapter reads a PDF, and whether a run happens at all. Both are this layer's by design
-- the adapter package says in its own docstring that choosing the scan path is "the
pipeline's decision, not a heuristic buried in here", and a tier limit is an operator's
policy rather than anything a parser could know.

What this module refuses to do:
  * It refuses to invent a metric, a pack, a document or a mapping.
  * It refuses to promote the `missing` lane. Bulk-accept takes `review` only -- a missing
    field has no value to accept, and `min_confidence=0` would otherwise sweep the whole
    third lane into `approved`, which is the silent error the gate exists to prevent.
  * It refuses to name a domain noun. Field names arrive from the pack (Law II).
  * It refuses to let a document it could not read look processed. A document that was
    ingested and yielded nothing we will claim reaches a human with the named reason, and
    is never reported as a clean zero.
  * It refuses to raise a refusal. A run blocked by configuration comes back as a batch
    that says so, because nothing in the API raises across its seam (CLAUDE.md 6).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict

from backend.api.deps import ExportFile, UploadedFile
from backend.api.eventlog import EventLog, new_event
from backend.api.repository import Repository
from backend.engine import packs as packs_module
from backend.engine import render as render_module
from backend.engine import rounds as rounds_module
from backend.engine.config import DEFAULT_TENANT, ConfigStore, control
from backend.engine.gate import DEFAULT_AUTO_THRESHOLD, DEFAULT_REVIEW_THRESHOLD
from backend.engine.ledger import Ledger, LedgerEntry, SqliteLedger
from backend.engine.contracts import (
    LearnedCorrection,
    AgentEvent,
    Authority,
    Batch,
    BatchFile,
    BatchStats,
    BulkAcceptPayload,
    BulkAcceptResponse,
    CreateBatchPayload,
    DatasetRecord,
    Document,
    HealthLayer,
    HomeStats,
    InsightRun,
    Insights,
    Mapping,
    MappingPatchPayload,
    MappingPatchResponse,
    PaginatedResponse,
    ReviewQueueItem,
    SchemaPack,
    SourceLocationPdf,
    Unavailable,
)
from backend.eval import score as score_module
from backend.memory.feedback import apply_patch
from backend.memory.precedents import PrecedentStore, SqlitePrecedentStore
from backend.pipeline import process_document

if TYPE_CHECKING:  # the adapters are imported lazily; these are for the signature only
    from backend.adapters.pdf_scan import ScanPage, VisionOutcome

#: Formats we can accept an upload of. A file outside this set is marked unsupported on
#: that document and the batch continues (CLAUDE.md 6).
_ACCEPTED_SUFFIXES = {".csv", ".xlsx", ".xls", ".html", ".htm", ".pdf", ".txt"}

_SUFFIX_TO_TYPE = {
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".txt": "txt",
}

#: Suffix -> the media type the adapter package dispatches on. Kept here rather than
#: guessed from the OS mimetypes table, which disagrees with itself across platforms and
#: would make a document readable on one machine and unsupported on another.
_SUFFIX_TO_MEDIA_TYPE = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


_PDF_MEDIA_TYPE = _SUFFIX_TO_MEDIA_TYPE[".pdf"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _suffix(name: str) -> str:
    _, _, tail = name.rpartition(".")
    return f".{tail.lower()}" if tail and tail != name else ""


def _as_number(raw: Any, fallback: float) -> float:
    """A control's value as a number, or the stated default.

    An explicit empty value is a value everywhere else in config.py, but there is no such
    thing as an empty threshold, so "" falls back to the stated default rather than to
    zero -- a zero auto threshold would silently auto-accept the entire run.
    """
    try:
        text = str(raw).strip()
        return fallback if text == "" or text.lower() == "none" else float(text)
    except (TypeError, ValueError):
        return fallback


class RunRefusal(BaseModel):
    """Why a whole run was refused before a single document was read.

    A refusal is data, not an exception. `create_batch` turns one into a batch that carries
    the reason on every file, so the caller gets a typed result and the three handlers in
    `main.py` never see it -- they are the outer seam, not the error path (CLAUDE.md 6).

    Both conditions this carries are the operator's configuration rather than anything
    about the files, which is why they are decided ABOVE the first batch-row write: the
    same rule a malformed pack follows, for the same reason. A run blocked before any
    document is read leaves nothing half-written behind it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    detail: str


class UnclaimedDocument(BaseModel):
    """A document that was ingested and from which we will claim no value at all.

    Not an error and not a clean zero, which are the only two things `FileStatus` can say.
    The file reads `unsupported` -- the file is fine, our ability to read it was not -- and
    the reason travels to a human as a `review`-lane row, because the review tray is the
    only review surface the contract has. A document reported `done` with no fields is the
    exact silence the three lanes exist to prevent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    detail: str
    page_count: int | None = None


def _review_row_for(
    unclaimed: UnclaimedDocument,
    *,
    document_id: str,
    source_label: str,
    media_type: str,
) -> Mapping:
    """One review-lane row standing for a document nothing could be read from.

    It claims nothing: no target field, no value, confidence zero. That is a legitimate
    review row and the most common one when intelligence is unavailable -- see
    docs/AGREEMENTS.md 6b, where an empty `target_field` on a review row is exactly the
    case the contract was extended to let an analyst resolve.

    `source_label` is the document's own name, because no label was read off the page and
    inventing one would be this layer deciding what the document says. The reviewer is
    being asked about the document, so the row names the document.
    """
    return Mapping(
        id=f"map-{uuid.uuid4().hex[:12]}",
        document_id=document_id,
        # Empty means "this document is a single record", which is the honest degenerate
        # case: nothing was read, so there are no records to tell apart.
        record_key="",
        source_label=source_label,
        target_field="",
        raw_value="",
        value="",
        confidence=0.0,
        status="review",
        reason=unclaimed.detail,
        # The page exists and the whole of it is what went unread, so the box is the page.
        # This locates the refusal, not a value -- no value is claimed, which is why the
        # contract does not require provenance for this lane at all.
        source_location=(
            SourceLocationPdf(page=1, bbox=(0.0, 0.0, 1.0, 1.0))
            if unclaimed.page_count and media_type == _PDF_MEDIA_TYPE
            else None
        ),
    )


class PersistedService:
    """Satisfies PipelineService by reading the repository and the pack. Nothing else."""

    def __init__(
        self,
        *,
        repository: Repository,
        event_log: EventLog,
        config_store: ConfigStore | None = None,
        precedents: PrecedentStore | None = None,
        ledger: Ledger | None = None,
    ) -> None:
        self._repo = repository
        self._events = event_log
        self._config_store = config_store
        self._precedents = precedents or SqlitePrecedentStore()
        self._ledger = ledger or SqliteLedger()

    # -- packs -----------------------------------------------------------------

    def _active_pack_or_reason(self) -> tuple[packs_module.Pack | None, str | None]:
        """The governing pack, or None and the loader's own reason for refusing.

        The reason is carried rather than discarded because the two cases are not the
        same problem and do not have the same fix: a malformed pack needs its YAML
        corrected, while several valid packs need an operator to say which one governs.
        Substituting one sentence for both sends whoever reads it hunting for a broken
        file that does not exist.
        """
        try:
            configured = control("active_pack_id", store=self._config_store).value
            return packs_module.resolve_active_pack(configured or ""), None
        except Exception as exc:
            return None, str(exc).strip() or type(exc).__name__

    def _active_pack(self) -> packs_module.Pack | None:
        """The pack that governs a run, or None if none is loadable.

        Returns None rather than raising: a malformed pack must block a RUN, not the
        Schema page that a human needs in order to see what is wrong with it.
        """
        return self._active_pack_or_reason()[0]

    def list_packs(self, *, tenant_id: str = DEFAULT_TENANT) -> list[SchemaPack]:
        try:
            loaded = packs_module.load_packs()
        except Exception:
            return []
        return [packs_module.to_schema_pack(pack) for pack in loaded.values()]

    def get_pack(self, pack_id: str, *, tenant_id: str = DEFAULT_TENANT) -> SchemaPack | None:
        for pack in self.list_packs(tenant_id=tenant_id):
            if pack.id == pack_id:
                return pack
        return None

    def put_pack(
        self, pack_id: str, patch: dict[str, Any], *, tenant_id: str = DEFAULT_TENANT
    ) -> SchemaPack | None:
        """Not implemented here, on purpose: a human authors a pack, not an endpoint.

        A drafted declaration is born PROPOSED and takes effect when a person accepts it
        (Law III). Writing a pack edit straight to disk from a PATCH would make us the
        author of the customer's meaning, so this returns the pack unchanged until the
        accept-a-proposal flow exists.
        """
        return self.get_pack(pack_id, tenant_id=tenant_id)

    def _field_order(self) -> list[str]:
        pack = self._active_pack()
        return [declaration.name for declaration in pack.fields] if pack else []

    # -- batches ---------------------------------------------------------------

    def list_batches(self, *, tenant_id: str = DEFAULT_TENANT) -> list[Batch]:
        return self._repo.list_batches(tenant_id=tenant_id)

    def get_batch(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Batch | None:
        return self._repo.get_batch(batch_id, tenant_id=tenant_id)

    def create_batch(
        self,
        payload: CreateBatchPayload,
        files: Sequence[UploadedFile],
        *,
        tenant_id: str = DEFAULT_TENANT,
    ) -> Batch:
        """Accept the upload, then actually run it: extract, map, resolve, persist.

        Processing happens per document, through `pipeline.process_document`, which takes
        ONE document -- so moving this to a Cloud Run job or an Eventarc handler is a
        wrapper around the same loop rather than a rewrite (CLAUDE.md 6b).

        A file that cannot be read marks THAT document and the batch continues. One bad
        file never ends a run, and the reason is recorded on the document and as an event
        rather than raised.
        """
        pack, pack_reason = self._active_pack_or_reason()
        seam = self._inference_seam(tenant_id)

        # Every operator-settable thing this run obeys is resolved HERE, once, before a
        # byte of any document is read. Two of them can refuse the run outright, and both
        # are decided above the first batch-row write for the same reason a malformed pack
        # blocks a run before any document is read: a refusal discovered half way through
        # leaves rows behind it.
        auto_threshold, review_threshold = self._gate_thresholds()
        quota, used = self._document_metering(tenant_id)
        page_limit = self._synchronous_page_limit()

        refusal: RunRefusal | None = None
        if review_threshold > auto_threshold:
            # gate.decide raises on this pair -- correctly, since the middle lane would be
            # empty and Law V would be a boolean in disguise. Now that operator values
            # actually reach it, the pair is checked at this seam so the exception cannot
            # be the thing the caller finds out through.
            refusal = RunRefusal(
                code="thresholds_inverted",
                detail=(
                    f"the review threshold {review_threshold:.2f} is above the auto "
                    f"threshold {auto_threshold:.2f}, which would leave the review lane "
                    "empty and make the three lanes a boolean in disguise. Nothing was "
                    "read; set the two thresholds the other way round and run again"
                ),
            )
        elif 0 < quota <= used:
            refusal = RunRefusal(
                code="quota_exhausted",
                detail=(
                    f"the monthly allowance of {quota} document(s) is used up: {used} "
                    "already ingested this month. What is metered is documents rather "
                    "than pages, because four of the six readable formats report no page "
                    "count at all. Nothing in this upload was read"
                ),
            )
        if refusal is not None:
            return self._refused_batch(payload, files, refusal, tenant_id=tenant_id)

        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        stamp = _now()

        # The batch row goes in BEFORE any document is read, and that ordering is
        # load-bearing. Written last, a crash part-way through leaves documents and
        # mappings whose parent batch does not exist: invisible to every per-batch screen,
        # yet still counted by the tenant-wide queries behind the review queue and the home
        # stats. The tray then shows rows a reviewer cannot open. Written first, a crash
        # leaves a batch that is visibly incomplete, which is a state someone can act on.
        self._repo.upsert_batch(
            Batch(
                id=batch_id,
                name=f"Upload {stamp[:19]}",
                pack_id=pack.id if pack else payload.pack_id,
                pack_name=pack.name if pack else payload.pack_id,
                files=[],
                stage="ingesting",
                status="running",
                created_at=stamp,
                updated_at=stamp,
            ),
            tenant_id=tenant_id,
        )

        batch_files: list[BatchFile] = []
        total_fields = auto = review = missing = not_reportable = 0
        model_calls = precedents_applied = 0
        read_any = False
        ingested = 0

        for index, upload in enumerate(files):
            suffix = _suffix(upload.name)
            document_id = f"doc-{uuid.uuid4().hex[:12]}"
            file_id = f"file-{index}-{uuid.uuid4().hex[:8]}"
            declared_type = _SUFFIX_TO_TYPE.get(suffix, suffix.lstrip(".") or "unknown")

            if suffix not in _ACCEPTED_SUFFIXES:
                batch_files.append(
                    BatchFile(
                        id=file_id,
                        name=upload.name,
                        type=declared_type,
                        size=upload.size_bytes,
                        status="unsupported",
                        error=f"no adapter handles {suffix or 'this file'}",
                    )
                )
                continue

            # The allowance is per document, so an upload that would cross the line is cut
            # at the line rather than waved through whole. Checked here, above the document
            # row and above the read: a file this refuses is never opened and never
            # counted. A file no adapter handles was not ingested either, which is why
            # this sits below that check and not above it.
            if 0 < quota <= used + ingested:
                batch_files.append(
                    BatchFile(
                        id=file_id,
                        name=upload.name,
                        type=declared_type,
                        size=upload.size_bytes,
                        status="unsupported",
                        error=(
                            f"the monthly allowance of {quota} document(s) was reached "
                            "earlier in this upload, so this file was not read"
                        ),
                    )
                )
                continue
            ingested += 1

            document = Document(
                id=document_id,
                batch_id=batch_id,
                name=upload.name,
                type=_SUFFIX_TO_TYPE.get(suffix, "txt"),
                file_url="",
                status="processing",
                created_at=stamp,
            )
            self._repo.upsert_document(document, tenant_id=tenant_id)

            media_type = _SUFFIX_TO_MEDIA_TYPE.get(suffix, "application/octet-stream")
            file_status: str = "done"
            error: str | None = None

            try:
                from backend.adapters import extract_document

                extracted = extract_document(
                    upload.content, media_type, document_id=document_id
                )
            except Exception as exc:  # containment: this document only
                extracted = None
                file_status, error = "error", f"{type(exc).__name__}: {exc}"

            # The scan route, and the reason it lives here. Both PDF adapters claim
            # application/pdf and the dispatch table holds only the text one, deliberately:
            # the adapter package's own docstring says choosing the scan path is the
            # pipeline's decision and not a heuristic buried in there. This is the pipeline.
            #
            # The discriminator is a text layer that produced nothing on a page that really
            # exists. It is a fact rather than a guess, because both PDF adapters now treat
            # zero PAGES as an error -- a damaged PDF opens in PyMuPDF with no pages
            # instead of raising, which used to read as "processed, nothing in it" -- while
            # zero FACTS on a real page stays a legitimate `done`.
            if (
                extracted is not None
                and extracted.status == "done"
                and (extracted.page_count or 0) > 0
                and not extracted.facts
            ):
                extracted = self._read_as_scan(
                    upload.content,
                    media_type,
                    document_id=document_id,
                    seam_present=seam is not None,
                )

            #: Set when the document was ingested and nothing will be claimed from it.
            unclaimed: UnclaimedDocument | None = None

            if extracted is not None and extracted.status == "unavailable":
                # `unavailable` is not `error`: the file is fine and a dependency of
                # reading it is not. So the file is reported `unsupported` -- the nearest
                # thing FileStatus can say to "we could not read this, and that is not the
                # file's fault" -- and the actual outcome goes to a human below.
                reason = extracted.unavailable or Unavailable(reason="provider-down")
                unclaimed = UnclaimedDocument(
                    code=reason.reason,
                    detail=(
                        f"this document was rasterized and not read ({reason.reason}): "
                        f"{reason.detail or 'no detail was reported'}. No value is claimed "
                        "from it"
                    ),
                    page_count=extracted.page_count,
                )
                file_status, error = "unsupported", unclaimed.detail
            elif extracted is not None and extracted.status != "done":
                file_status = "unsupported" if extracted.status == "unsupported" else "error"
                error = extracted.error or extracted.status

            if extracted is not None and extracted.status == "done":
                pages = extracted.page_count or 0
                if 0 < page_limit < pages:
                    # The honest long-document branch. There is no asynchronous processor
                    # in this build, so this does not queue the document and does not
                    # claim to: it refuses to map it inline and says so. The parse is what
                    # told us the page count and is cheap; the mapping pass is the part
                    # that would not finish inside a request, so that is the part the
                    # limit governs -- and this branch is exactly where a real async
                    # processor would be called instead.
                    unclaimed = UnclaimedDocument(
                        code="above-synchronous-page-limit",
                        detail=(
                            f"{pages} pages is above the synchronous limit of {page_limit}, "
                            "so this document was not processed inline. It was not queued "
                            "either -- there is no asynchronous processor yet -- so it "
                            "needs a human to decide what to do with it"
                        ),
                        page_count=pages,
                    )
                    file_status, error = "unsupported", unclaimed.detail
                elif pack is None:
                    file_status, error = "error", pack_reason or "no governing pack"
                else:
                    read_any = True
                    outcome = process_document(
                        document_id,
                        extracted.facts,
                        pack=pack,
                        precedents=self._precedents,
                        seam=seam,
                        tenant_id=tenant_id,
                        document_name=upload.name,
                        # The two thresholds as the operator set them. The gate refuses to
                        # read config -- it is a pure function of its inputs -- so the
                        # resolution has to happen at this seam and be passed in. Without
                        # this the Settings page could move both, settings and health
                        # reported the new value with its source, and the run used
                        # gate.py's module constants regardless: a control the UI asserted
                        # and the pipeline ignored.
                        auto_threshold=auto_threshold,
                        review_threshold=review_threshold,
                        # Stays False, deliberately. Nothing has been fitted against the
                        # golden set, which is still 0 of 30 confirmed. Making the gate
                        # configurable and its provenance false in the same change would
                        # be worse than the bug being fixed here.
                        thresholds_are_calibrated=False,
                    )
                    for resolution in outcome.resolutions:
                        self._repo.upsert_mapping(resolution.mapping, tenant_id=tenant_id)
                        self._record_evidence(
                            resolution, batch_id=batch_id, pack=pack, tenant_id=tenant_id
                        )
                        total_fields += 1
                        if resolution.mapping.status in ("auto", "approved"):
                            auto += 1
                        elif resolution.mapping.status == "review":
                            review += 1
                        else:
                            missing += 1
                    not_reportable += len(outcome.not_reportable)
                    model_calls += outcome.counters.model_calls_made
                    precedents_applied += outcome.counters.precedents_applied

                    self._events.emit(
                        batch_id,
                        new_event(
                            agent="mapper",
                            step="mapped",
                            status="done",
                            message=(
                                f"{upload.name}: {len(outcome.resolutions)} field(s) "
                                f"resolved, {len(outcome.not_reportable)} label(s) were "
                                f"not reportable fields, {outcome.counters.model_calls_made} "
                                "model call(s)"
                            ),
                            file_id=file_id,
                        ),
                        tenant_id=tenant_id,
                    )

            if unclaimed is not None:
                # The outcome reaches a human instead of the file simply looking empty.
                # Counted in the review lane so the tray and the batch stats reconcile --
                # a row the tray shows and the stats do not is how orphan rows hid before.
                # Deliberately not written to the ledger: the ledger defends values, and
                # this row claims none.
                self._repo.upsert_mapping(
                    _review_row_for(
                        unclaimed,
                        document_id=document_id,
                        source_label=upload.name,
                        media_type=media_type,
                    ),
                    tenant_id=tenant_id,
                )
                total_fields += 1
                review += 1
                self._events.emit(
                    batch_id,
                    new_event(
                        agent="ingest",
                        step="unclaimed",
                        status="done",
                        message=f"{upload.name}: {unclaimed.detail}",
                        file_id=file_id,
                    ),
                    tenant_id=tenant_id,
                )
            elif error:
                self._events.emit(
                    batch_id,
                    new_event(
                        agent="ingest",
                        step="unreadable",
                        status="error",
                        message=f"{upload.name}: {error}",
                        file_id=file_id,
                    ),
                    tenant_id=tenant_id,
                )

            self._repo.upsert_document(
                document.model_copy(
                    update={
                        "status": file_status,
                        # What the reader actually reported, not an assumption. None stays
                        # None: four of the six adapters have no page concept, and writing
                        # a number for them would be inventing one.
                        "page_count": extracted.page_count if extracted else None,
                    }
                ),
                tenant_id=tenant_id,
            )
            batch_files.append(
                BatchFile(
                    id=file_id,
                    name=upload.name,
                    type=declared_type,
                    size=upload.size_bytes,
                    status=file_status,
                    progress=100,
                    document_id=document_id,
                    error=error,
                )
            )

        batch = Batch(
            id=batch_id,
            name=f"Upload {stamp[:19]}",
            pack_id=pack.id if pack else payload.pack_id,
            pack_name=pack.name if pack else payload.pack_id,
            files=batch_files,
            # `ready` only if something was actually read. A batch where every file failed
            # reports `failed`, because a green batch containing nothing is the kind of
            # result a demo repeats without noticing.
            stage="ready" if read_any else "failed",
            status="done" if read_any else "failed",
            created_at=stamp,
            updated_at=_now(),
            stats=BatchStats(
                total_files=len(batch_files),
                total_fields=total_fields,
                auto_approved=auto,
                needs_review=review,
                missing=missing,
            ),
        )
        self._repo.upsert_batch(batch, tenant_id=tenant_id)

        self._events.emit(
            batch_id,
            new_event(
                agent="ingest",
                step="complete",
                status="done" if read_any else "error",
                message=(
                    f"{len(batch_files)} file(s): {total_fields} field(s) resolved "
                    f"({auto} auto, {review} review, {missing} missing), "
                    f"{not_reportable} label(s) not reportable, "
                    f"{model_calls} model call(s), "
                    f"{precedents_applied} precedent(s) applied, "
                    # Measured from this run's own auto-accepted counter, which is the one
                    # thing that did save an analyst time -- a field that went to review
                    # saved nothing, because they still looked at it.
                    f"{self._minutes_saved_from(auto)} analyst minute(s) saved"
                ),
            ),
            tenant_id=tenant_id,
        )
        return batch

    # -- what the operator controls -------------------------------------------

    def _gate_thresholds(self) -> tuple[float, float]:
        """The two lane thresholds as the operator set them, with gate.py's as the default.

        Resolved at this seam because the gate refuses to read config: it is a pure
        function of its inputs so a test can pin it without a database. That means
        somebody has to hand it the numbers, and if nobody does, the module constants
        answer instead and the control is decorative.
        """
        return (
            _as_number(
                control("gate_auto_threshold", store=self._config_store).value,
                DEFAULT_AUTO_THRESHOLD,
            ),
            _as_number(
                control("gate_review_threshold", store=self._config_store).value,
                DEFAULT_REVIEW_THRESHOLD,
            ),
        )

    def _synchronous_page_limit(self) -> int:
        """How many pages this layer will map inside one request. 0 or less means no limit.

        Honest about what it governs. The parse is cheap and is what tells us the page
        count; the mapping pass is the part that would not finish inside a request, so
        that is the part this limit refuses. There is no asynchronous processor in this
        build, so a document above the limit is not queued and is never said to be.
        """
        return int(_as_number(control("async_page_threshold", store=self._config_store).value, 0))

    def _document_metering(self, tenant_id: str) -> tuple[int, int]:
        """(allowance, documents already ingested this month). Allowance <= 0 is unmetered.

        Documents rather than pages, and the control is named for it: page_count is
        reported by the two PDF adapters and left None by the other four, so a page quota
        would meter four of six formats at zero -- and an uncounted document is
        indistinguishable from a free one.
        """
        return (
            int(_as_number(control("monthly_document_quota", store=self._config_store).value, 0)),
            self._repo.documents_this_month(tenant_id=tenant_id),
        )

    def _minutes_saved_from(self, auto_accepted: int) -> float:
        """Analyst minutes saved, from a counter and the control. Never from a benchmark.

        The rate is the `analyst_minutes_per_field` control, so the figure behind a scored
        criterion is an operator's stated assumption rather than a number chosen in here.
        Zero auto-accepted fields is zero minutes saved and that is a count, not an
        estimate: nothing was accepted, so nothing was skipped.
        """
        minutes = _as_number(
            control("analyst_minutes_per_field", store=self._config_store).value, 0.0
        )
        return rounds_module.analyst_minutes_saved(auto_accepted, minutes)

    def _read_as_scan(
        self, data: bytes, media_type: str, *, document_id: str, seam_present: bool
    ):
        """The second attempt at a PDF: rasterize it and hand each page to a reader.

        Imported inside the function, like the dispatch call above it, so importing this
        service needs none of the adapters' parser dependencies.
        """
        from backend.adapters import pdf_scan

        return pdf_scan.extract_document(
            data,
            media_type,
            document_id=document_id,
            vision=self._vision_reader(seam_present=seam_present),
        )

    def _vision_reader(self, *, seam_present: bool) -> Callable[[ScanPage], VisionOutcome]:
        """The reader injected into `pdf_scan`. It resolves the model, then says it cannot see.

        Stated plainly, because the alternative is a claim nobody can defend: **no vision
        call is made anywhere in this build.** There is no vision backend behind this
        function. What routing a scanned PDF here buys is that the document is rasterized,
        reaches a named `Unavailable` and lands in front of a human, instead of reporting
        zero facts and reading as a document that was processed and simply had nothing on
        it. It does not read the scan.

        The model is resolved from the `vision_model` control rather than named here,
        because the model used on a scanned page is the one most likely to need changing on
        the day, and a model that cannot be changed from the Settings page cannot be
        changed at all.

        The reason is named rather than generic: with no key the honest state is `no-key`,
        and with a key resolved it is `model-unavailable` -- the model is configured and
        simply not callable from here. Both route to review; neither is a guess.
        """
        model = str(control("vision_model", store=self._config_store).value or "")
        reason = "model-unavailable" if seam_present else "no-key"

        def read(page: ScanPage) -> VisionOutcome:
            return Unavailable(
                reason=reason,
                detail=(
                    f"page {page.page} was rasterized at {page.dpi} dpi and not read: "
                    f"vision model {model or 'unset'!r} is configured but no vision "
                    "backend is wired into this build"
                ),
            )

        return read

    def _refused_batch(
        self,
        payload: CreateBatchPayload,
        files: Sequence[UploadedFile],
        refusal: RunRefusal,
        *,
        tenant_id: str,
    ) -> Batch:
        """The typed refusal, as the one thing the seam is allowed to return: a Batch.

        Persisted, and complete rather than partial. A refusal that returned an id nothing
        could open would send the UI to a batch page that 404s, and a refusal that wrote
        nothing at all would leave a caller holding a batch the batch list has never heard
        of. Every file carries the reason, because the per-file error is where a person
        actually reads it.
        """
        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        stamp = _now()
        pack = self._active_pack()
        refused = [
            BatchFile(
                id=f"file-{index}-{uuid.uuid4().hex[:8]}",
                name=upload.name,
                type=_SUFFIX_TO_TYPE.get(_suffix(upload.name), "txt"),
                size=upload.size_bytes,
                status="unsupported",
                error=refusal.detail,
            )
            for index, upload in enumerate(files)
        ]
        batch = Batch(
            id=batch_id,
            name=f"Upload {stamp[:19]}",
            pack_id=pack.id if pack else payload.pack_id,
            pack_name=pack.name if pack else payload.pack_id,
            files=refused,
            stage="failed",
            status="failed",
            created_at=stamp,
            updated_at=stamp,
            stats=BatchStats(
                total_files=len(refused),
                total_fields=0,
                auto_approved=0,
                needs_review=0,
                missing=0,
            ),
        )
        self._repo.upsert_batch(batch, tenant_id=tenant_id)
        self._events.emit(
            batch_id,
            new_event(
                agent="ingest",
                step="refused",
                status="error",
                message=f"{refusal.code}: {refusal.detail}",
            ),
            tenant_id=tenant_id,
        )
        return batch

    def _record_evidence(
        self,
        resolution,
        *,
        batch_id: str,
        pack: packs_module.Pack,
        tenant_id: str,
    ) -> None:
        """Append one append-only ledger entry per cell. This is the audit story.

        Without this the ledger is an empty table and "click the cell to see the page, the
        rule that fired, the model and who approved it" has nothing behind it. It also
        carries the authority, which is the only place `patch_mapping` can later learn
        whether a field came from the pack or from a model -- `Mapping` has no authority
        field, because types.ts does not declare one.

        Never raises: losing an audit row must not fail a run that otherwise succeeded,
        and the mapping itself is already persisted by the time we get here.
        """
        mapping = resolution.mapping
        try:
            self._ledger.append(
                LedgerEntry(
                    tenant_id=tenant_id,
                    run_id=batch_id,
                    document_id=mapping.document_id,
                    mapping_id=mapping.id,
                    record_key=mapping.record_key,
                    source_label=mapping.source_label,
                    target_field=mapping.target_field,
                    raw_value=mapping.raw_value,
                    raw_unit=mapping.raw_unit,
                    value=mapping.value,
                    unit=mapping.unit,
                    status=mapping.status,
                    confidence=mapping.confidence,
                    authority=resolution.authority.name if resolution.authority else None,
                    conversion_rule_id=(
                        mapping.conversion.rule_id if mapping.conversion else None
                    ),
                    formula_text=(
                        mapping.conversion.formula_text if mapping.conversion else None
                    ),
                    source_location=(
                        mapping.source_location.model_dump(mode="json")
                        if mapping.source_location
                        else None
                    ),
                    pack_id=pack.id,
                    pack_version=pack.version,
                    reason=mapping.reason,
                )
            )
        except Exception:
            pass

    def _prior_authority(self, mapping_id: str, tenant_id: str) -> Authority | None:
        """What decided this field, read from the ledger.

        `patch_mapping` needs it so that accepting a field the pack already resolved does
        not write a precedent: a pack rule outranks a precedent, so such a precedent could
        never be the thing that resolved the field, and counting it would inflate
        precedents_applied with entries that did no work.
        """
        try:
            for entry in self._ledger.by_mapping(mapping_id, tenant_id=tenant_id):
                if entry.authority:
                    return Authority[entry.authority]
        except Exception:
            pass
        return None

    def _inference_seam(self, tenant_id: str):
        """A configured Seam, or None when no key resolves.

        Returning None rather than a Seam that will fail keeps the no-key path free of a
        pointless request per field: with nothing configured the deterministic routes
        still resolve and the rest goes to review, which is what README section 7
        promises. Built lazily, never at import.
        """
        try:
            from backend.engine.config import SECRETS, secret_for
            from backend.intelligence.base import Seam

            provider = str(control("provider", store=self._config_store).value or "")
            secret_id = f"{provider}_api_key"
            if secret_id not in SECRETS:
                return None
            if not (secret_for(secret_id, store=self._config_store, tenant_id=tenant_id).value or ""):
                return None
            return Seam.from_config(store=self._config_store, tenant_id=tenant_id)
        except Exception:
            return None

    def cancel_batch(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Batch | None:
        batch = self._repo.get_batch(batch_id, tenant_id=tenant_id)
        if batch is None:
            return None
        cancelled = batch.model_copy(update={"status": "cancelled", "updated_at": _now()})
        self._repo.upsert_batch(cancelled, tenant_id=tenant_id)
        return cancelled

    def batch_events(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> list[AgentEvent] | None:
        if self._repo.get_batch(batch_id, tenant_id=tenant_id) is None:
            return None
        return self._repo.list_events(batch_id, tenant_id=tenant_id, after_seq=after_seq)

    def batch_records(
        self,
        batch_id: str,
        *,
        page: int = 1,
        per_page: int = 50,
        tenant_id: str = DEFAULT_TENANT,
    ) -> PaginatedResponse[DatasetRecord] | None:
        if self._repo.get_batch(batch_id, tenant_id=tenant_id) is None:
            return None

        mappings = self._repo.list_mappings(tenant_id=tenant_id, batch_id=batch_id)
        documents = {
            document.id: document
            for document in self._repo.list_documents(batch_id, tenant_id=tenant_id)
        }
        order = self._field_order()

        rows: list[DatasetRecord] = []
        # Grouped by (document, record), not by document. One source document can hold
        # many records; grouping by document alone showed one row of thirty and let the
        # last value written win.
        grouped: dict[tuple[str, str], list[Mapping]] = {}
        for mapping in mappings:
            grouped.setdefault((mapping.document_id, mapping.record_key), []).append(mapping)

        for document_id, record_key in sorted(grouped):
            group = grouped[(document_id, record_key)]
            values: dict[str, Any] = {}
            worst: str = "auto"
            page_number: int | None = None
            cell: str | None = None
            for mapping in group:
                if mapping.target_field:
                    values[mapping.target_field] = mapping.value
                # The row's status is the least settled of its fields: a row with one
                # flagged field is not an auto-accepted row.
                if mapping.status == "missing" or worst == "missing":
                    worst = "missing"
                elif mapping.status == "review":
                    worst = "review"
                location = mapping.source_location
                if location is not None and location.type == "pdf" and page_number is None:
                    page_number = location.page
                if location is not None and location.type == "sheet" and cell is None:
                    cell = location.cell

            document = documents.get(document_id)
            rows.append(
                DatasetRecord(
                    # The record is the row's identity now, not the document. Stable
                    # across re-runs, so the UI can keep a selection and the ledger can be
                    # joined back to the row a reviewer is looking at.
                    id=f"{document_id}:{record_key}" if record_key else document_id,
                    document_id=document_id,
                    document_name=document.name if document else document_id,
                    _status=worst,
                    _source_page=page_number,
                    _source_cell=cell,
                    **{field: values.get(field) for field in order},
                )
            )

        start = max(0, (page - 1) * per_page)
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
        if self._repo.get_batch(batch_id, tenant_id=tenant_id) is None:
            return None
        mappings = self._repo.list_mappings(tenant_id=tenant_id, batch_id=batch_id)
        order = self._field_order()
        if fmt == "json":
            return ExportFile(
                filename=f"{batch_id}.json",
                media_type="application/json",
                content=render_module.render_json(mappings, order, audit=audit),
            )
        return ExportFile(
            filename=f"{batch_id}.csv",
            media_type="text/csv",
            content=render_module.render_csv(mappings, order, audit=audit),
        )

    # -- documents -------------------------------------------------------------

    def get_document(
        self, document_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> Document | None:
        return self._repo.get_document(document_id, tenant_id=tenant_id)

    def document_mappings(
        self, document_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> list[Mapping] | None:
        if self._repo.get_document(document_id, tenant_id=tenant_id) is None:
            return None
        return self._repo.list_mappings(tenant_id=tenant_id, document_id=document_id)

    # -- mappings --------------------------------------------------------------

    def patch_mapping(
        self,
        mapping_id: str,
        payload: MappingPatchPayload,
        *,
        tenant_id: str = DEFAULT_TENANT,
    ) -> MappingPatchResponse | None:
        """A real correction: it writes a FeedbackEvent and, where there is a lesson, a
        precedent. `learned=False` is a legitimate answer and is never faked."""
        mapping = self._repo.get_mapping(mapping_id, tenant_id=tenant_id)
        if mapping is None:
            return None

        outcome = apply_patch(
            mapping,
            payload,
            self._precedents,
            prior_authority=self._prior_authority(mapping_id, tenant_id),
        )
        self._repo.upsert_mapping(outcome.response.mapping, tenant_id=tenant_id)
        self._repo.append_feedback(outcome.event, tenant_id=tenant_id)
        return outcome.response

    def bulk_accept(
        self, payload: BulkAcceptPayload, *, tenant_id: str = DEFAULT_TENANT
    ) -> BulkAcceptResponse | None:
        if self._repo.get_document(payload.document_id, tenant_id=tenant_id) is None:
            return None

        # `review` only. Never `missing`: see the module docstring.
        candidates = [
            mapping
            for mapping in self._repo.list_mappings(
                tenant_id=tenant_id, document_id=payload.document_id, statuses=("review",)
            )
            if mapping.confidence >= payload.min_confidence
        ]

        accepted: list[Mapping] = []
        for mapping in candidates:
            outcome = apply_patch(
                mapping,
                MappingPatchPayload(action="accept"),
                self._precedents,
                prior_authority=self._prior_authority(mapping.id, tenant_id),
            )
            self._repo.upsert_mapping(outcome.response.mapping, tenant_id=tenant_id)
            self._repo.append_feedback(outcome.event, tenant_id=tenant_id)
            accepted.append(outcome.response.mapping)

        return BulkAcceptResponse(accepted_count=len(accepted), mappings=accepted)

    def review_queue(self, *, tenant_id: str = DEFAULT_TENANT) -> list[ReviewQueueItem]:
        documents: dict[str, Document] = {}
        items: list[ReviewQueueItem] = []
        for mapping in self._repo.list_mappings(
            tenant_id=tenant_id, statuses=("review", "missing")
        ):
            document = documents.get(mapping.document_id)
            if document is None:
                document = self._repo.get_document(mapping.document_id, tenant_id=tenant_id)
                if document is not None:
                    documents[mapping.document_id] = document
            items.append(
                ReviewQueueItem(
                    mapping_id=mapping.id,
                    document_id=mapping.document_id,
                    document_name=document.name if document else mapping.document_id,
                    batch_id=document.batch_id if document else "",
                    record_key=mapping.record_key,
                    record_label=mapping.record_label,
                    source_label=mapping.source_label,
                    target_field=mapping.target_field,
                    reason=mapping.reason,
                    confidence=mapping.confidence,
                    status=mapping.status,
                )
            )
        return items

    # -- home and insights ----------------------------------------------------

    def _counted_lanes(self, tenant_id: str) -> tuple[int, int, int, int]:
        mappings = self._repo.list_mappings(tenant_id=tenant_id)
        auto = sum(1 for m in mappings if m.status in ("auto", "approved"))
        review = sum(1 for m in mappings if m.status == "review")
        missing = sum(1 for m in mappings if m.status in ("missing", "rejected"))
        return len(mappings), auto, review, missing

    def _measured_accuracy(self, tenant_id: str) -> float:
        """The scorer's number, or 0.0 because there is no measurement to report.

        Never a literal. If the golden set is not confirmed, score() refuses and this
        returns zero -- and `health_layers` carries the reason so the zero is explained
        rather than mistaken for a measured failure.
        """
        try:
            result = score_module.score(self._repo.list_mappings(tenant_id=tenant_id))
        except Exception:
            return 0.0
        return result.mapping_accuracy if isinstance(result, score_module.Score) else 0.0

    def home_stats(self, *, tenant_id: str = DEFAULT_TENANT) -> HomeStats:
        documents = sum(
            len(self._repo.list_documents(batch.id, tenant_id=tenant_id))
            for batch in self._repo.list_batches(tenant_id=tenant_id)
        )
        total, auto, review, _missing = self._counted_lanes(tenant_id)
        reports = self._repo.list_round_reports(tenant_id=tenant_id)
        delta = 0.0
        if len(reports) >= 2 and reports[-1].comparable and reports[-1].delta_vs_previous:
            delta = float(reports[-1].delta_vs_previous.get("mapping_accuracy", 0.0))

        return HomeStats(
            documents_processed=documents,
            auto_approved_pct=round(auto / total, 4) if total else 0.0,
            fields_needing_review=review,
            mapping_accuracy=self._measured_accuracy(tenant_id),
            mapping_accuracy_delta=delta,
            recent_batches=self._repo.list_batches(tenant_id=tenant_id)[:5],
        )

    def insights(self, *, tenant_id: str = DEFAULT_TENANT) -> Insights:
        reports = self._repo.list_round_reports(tenant_id=tenant_id)
        runs = [
            InsightRun(
                run_id=f"round-{report.round}",
                date=_now(),
                mapping_accuracy=report.mapping_accuracy,
                conversion_correctness=report.conversion_correctness,
                manual_effort_saved=report.analyst_minutes_saved,
                feedback_improvement=(
                    float((report.delta_vs_previous or {}).get("mapping_accuracy", 0.0))
                    if report.comparable
                    else 0.0
                ),
            )
            for report in reports
        ]
        latest = reports[-1] if reports else None
        _total, auto, _review, _missing = self._counted_lanes(tenant_id)
        return Insights(
            mapping_accuracy=latest.mapping_accuracy if latest else self._measured_accuracy(tenant_id),
            conversion_correctness=latest.conversion_correctness if latest else 0.0,
            # With no round report yet, this is still counted rather than absent: the
            # auto-accepted rows are in the repository and the rate is a declared control,
            # so the figure is a count times a stated assumption. It reads 0.0 only when
            # nothing has been auto-accepted, which is the honest zero -- and the Pipeline
            # health layer says so when no run has produced a mapping at all.
            manual_effort_saved=(
                latest.analyst_minutes_saved if latest else self._minutes_saved_from(auto)
            ),
            feedback_improvement=(
                float((latest.delta_vs_previous or {}).get("mapping_accuracy", 0.0))
                if latest and latest.comparable
                else 0.0
            ),
            runs=runs,
            # Every correction an analyst made, newest first. This was [] while the
            # precedent store was already filling, so the one screen whose job is to show
            # that the loop learned showed nothing -- the feedback claim had no evidence
            # on it. Read from feedback events rather than precedents because a REJECT
            # teaches nothing and writes no precedent, yet it is still a correction the
            # analyst made and should see.
            learned_corrections=self._learned_corrections(tenant_id),
        )

    def _learned_corrections(self, tenant_id: str) -> list[LearnedCorrection]:
        out: list[LearnedCorrection] = []
        for event in reversed(self._repo.list_feedback(tenant_id=tenant_id)):
            if not event.to_field:
                continue  # a reject teaches no field; it is not a learned correction
            out.append(
                LearnedCorrection(
                    id=event.id,
                    field=event.to_field,
                    from_value=event.from_field or "(unmapped)",
                    to_value=event.to_field,
                    document_name=event.document_id,
                    learned_at=getattr(event, "ts", None) or "",
                )
            )
            if len(out) >= 50:
                break
        return out

    # -- health ----------------------------------------------------------------

    def health_layers(self, *, tenant_id: str = DEFAULT_TENANT) -> list[HealthLayer]:
        """The layers only the pipeline can speak for, including why a metric is absent."""
        layers: list[HealthLayer] = []

        pack, pack_reason = self._active_pack_or_reason()
        layers.append(
            HealthLayer(
                name="Pack",
                status="ok" if pack else "down",
                message=(
                    f"{pack.id} v{pack.version} ({pack.status.lower()}), "
                    f"{len(pack.fields)} field(s) | source=packs/"
                    if pack
                    else f"{pack_reason or 'no governing pack'} | source=packs/"
                ),
            )
        )

        try:
            rows = score_module.load_golden_set()
            confirmed = len(score_module.confirmed_rows(rows))
            enough = confirmed >= score_module.MINIMUM_CONFIRMED_ROWS
            layers.append(
                HealthLayer(
                    name="Scoring",
                    status="ok" if enough else "degraded",
                    message=(
                        f"{confirmed}/{len(rows)} golden rows confirmed | source=golden_set.csv"
                        if enough
                        else f"{confirmed}/{len(rows)} golden rows confirmed, "
                        f"{score_module.MINIMUM_CONFIRMED_ROWS} required: no accuracy is "
                        "measured and every accuracy figure reads 0 | source=golden_set.csv"
                    ),
                )
            )
        except Exception as exc:
            layers.append(
                HealthLayer(
                    name="Scoring",
                    status="down",
                    message=f"golden set unreadable: {exc} | source=golden_set.csv",
                )
            )

        total, auto, review, missing = self._counted_lanes(tenant_id)
        layers.append(
            HealthLayer(
                name="Pipeline",
                status="degraded" if total == 0 else "ok",
                message=(
                    "no run has produced a mapping yet; every count is zero because "
                    "nothing has been processed | source=repository"
                    if total == 0
                    else f"{total} mapping(s): {auto} auto, {review} review, "
                    f"{missing} missing | source=repository"
                ),
            )
        )

        precedents = self._precedents.all_precedents(tenant_id=tenant_id)
        layers.append(
            HealthLayer(
                name="Memory",
                status="ok",
                message=f"{len(precedents)} precedent(s) learned | source=memory",
            )
        )
        return layers
