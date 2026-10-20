"""Batch routes: list, create, read, cancel, events, records, export.

Thin by rule (README section 5): every handler parses, calls one service method and
serializes. The only thing resembling logic in here is turning a FastAPI `UploadFile` into
`deps.UploadedFile` -- and refusing the ones too big to become one -- and `None` into a
typed 404, all of which exist precisely so that no logic has to live below them in the
engine or above them in the UI.

What these routes refuse to do:
  * They refuse to decide anything about a document. Stage, status, stats and events come
    from the service; a route that computed a stat would be a second source of truth.
  * They refuse to read a file bigger than the cap. The cap is a control, not a constant,
    so an operator moves it the way they move a gate threshold -- and the refusal is per
    file: it marks that one `unsupported` with its reason and the batch continues.
  * They refuse to stream a traceback. A missing batch is `ApiProblem.not_found`.
  * They refuse to guess an export format. `format` is a Literal, so `?format=xml` is a
    422 from the framework rather than a half-written file.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal, Sequence

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from backend.api.deps import (
    ApiProblem,
    PipelineService,
    UploadedFile,
    get_config_store,
    get_pipeline_service,
    get_tenant_id,
)
from backend.engine.config import CONTROLS, ConfigStore, control
from backend.engine.contracts import (
    AgentEvent,
    Batch,
    BatchFile,
    CreateBatchPayload,
    DatasetRecord,
    PaginatedResponse,
)

router = APIRouter(prefix="/api/batches", tags=["batches"])

Service = Annotated[PipelineService, Depends(get_pipeline_service)]
Tenant = Annotated[str, Depends(get_tenant_id)]
Store = Annotated[ConfigStore, Depends(get_config_store)]

#: The control that caps one upload. Named here so the refusal message can say which
#: setting to change, which is the difference between a dead end and an answer.
UPLOAD_CAP_CONTROL = "upload_max_bytes"


@router.get("", response_model=list[Batch])
def list_batches(service: Service, tenant_id: Tenant) -> list[Batch]:
    return service.list_batches(tenant_id=tenant_id)


def _mib(byte_count: int) -> str:
    return f"{byte_count / (1024 * 1024):.1f} MiB"


def _declared_type(name: str) -> str:
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return suffix or "unknown"


def _refusal(index: int, name: str, size_bytes: int, cap: int) -> BatchFile:
    """The over-size file, as a file in the batch rather than a failed request.

    `unsupported` and not `error`: nothing went wrong, we declined. The reason names the
    two numbers and the control that holds the second one, so the next step is obvious.
    """
    return BatchFile(
        id=f"file-{index}-{uuid.uuid4().hex[:8]}",
        name=name,
        type=_declared_type(name),
        size=size_bytes,
        status="unsupported",
        error=(
            f"{_mib(size_bytes)} is over the {_mib(cap)} limit for one upload "
            f"(control {UPLOAD_CAP_CONTROL}), so the file was not read"
        ),
    )


async def _read_payload(
    request: Request,
    pack_id: str | None,
    url: str | None,
    files: list[UploadFile] | None,
    *,
    cap_bytes: int,
) -> tuple[CreateBatchPayload, list[UploadedFile], list[BatchFile]]:
    """Accept the multipart form the UI sends, or a JSON body for curl and tests.

    `Frontend/src/api/client.ts` posts FormData with `pack_id`, optional `url` and repeated
    `files`. Supporting the JSON body too costs four lines and makes the endpoint drivable
    from a terminal, which is how it gets debugged on stage.

    The size check reads `upload.size`, which the multipart parser has already counted,
    and skips the `read()` when it is over the cap -- so an over-size file never becomes a
    `bytes` object in this process. (The body still arrives: refusing before the transfer
    is an ASGI-level concern, and the cap here is about what gets materialised and handed
    to a parser.) A caller that supplies no declared size is read and then measured, so
    the cap holds either way.
    """
    if pack_id is None:
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict) or "pack_id" not in body:
            raise ApiProblem(
                422,
                "pack_id is required, as a multipart form field or a JSON body key",
                code="invalid_payload",
                resource="batch",
            )
        payload = CreateBatchPayload.model_validate(body)
        return payload, [], []

    uploads: list[UploadedFile] = []
    refused: list[BatchFile] = []
    for index, upload in enumerate(files or []):
        name = upload.filename or "unnamed"
        declared = upload.size
        content: bytes | None = None
        if declared is None:
            content = await upload.read()
            declared = len(content)
        if declared > cap_bytes:
            refused.append(_refusal(index, name, declared, cap_bytes))
            continue
        if content is None:
            content = await upload.read()
        uploads.append(
            UploadedFile(
                name=name,
                media_type=upload.content_type or "application/octet-stream",
                size_bytes=len(content),
                content=content,
            )
        )
    return CreateBatchPayload(pack_id=pack_id, url=url or None), uploads, refused


def _cap_bytes(store: ConfigStore, tenant_id: str) -> int:
    """The cap, resolved like every other control. A broken value falls back to the spec."""
    resolved = control(UPLOAD_CAP_CONTROL, store=store, tenant_id=tenant_id)
    try:
        cap = int(resolved.value)
    except (TypeError, ValueError):
        cap = 0
    # A cleared or nonsensical control must not mean "no limit", which is how a cap
    # becomes decorative. The declared default answers instead.
    return cap if cap > 0 else int(CONTROLS[UPLOAD_CAP_CONTROL].default)


def _with_refusals(batch: Batch, refused: Sequence[BatchFile]) -> Batch:
    """Put the refused files back into the batch the service built.

    The refusal is a route-level fact -- the file never reached the service, because not
    reading it is the whole point -- but it is still a file the uploader sent, so it
    belongs in `files` with its reason and in the one stat that counts files.
    """
    if not refused:
        return batch
    update: dict[str, Any] = {"files": [*batch.files, *refused]}
    if batch.stats is not None:
        update["stats"] = batch.stats.model_copy(
            update={"total_files": batch.stats.total_files + len(refused)}
        )
    return batch.model_copy(update=update)


@router.post("", response_model=Batch, status_code=201)
async def create_batch(
    request: Request,
    service: Service,
    store: Store,
    tenant_id: Tenant,
    pack_id: Annotated[str | None, Form()] = None,
    url: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> Batch:
    payload, uploads, refused = await _read_payload(
        request, pack_id, url, files, cap_bytes=_cap_bytes(store, tenant_id)
    )
    batch = service.create_batch(payload, uploads, tenant_id=tenant_id)
    return _with_refusals(batch, refused)


@router.get("/{batch_id}", response_model=Batch)
def get_batch(batch_id: str, service: Service, tenant_id: Tenant) -> Batch:
    batch = service.get_batch(batch_id, tenant_id=tenant_id)
    if batch is None:
        raise ApiProblem.not_found("batch", batch_id)
    return batch


@router.get("/{batch_id}/events", response_model=list[AgentEvent])
def batch_events(
    batch_id: str,
    service: Service,
    tenant_id: Tenant,
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentEvent]:
    """A JSON array today; the UI polls. SSE later changes this handler and nothing else.

    The event SHAPE is already `AgentEvent`, the log is already append-only and ordered,
    and `after_seq` is already the resume cursor -- so the swap is: iterate
    `EventLog.stream()` and yield `data: {json}\\n\\n`.
    """
    events = service.batch_events(batch_id, tenant_id=tenant_id, after_seq=after_seq)
    if events is None:
        raise ApiProblem.not_found("batch", batch_id)
    return events


@router.post("/{batch_id}/cancel", response_model=Batch)
def cancel_batch(batch_id: str, service: Service, tenant_id: Tenant) -> Batch:
    batch = service.cancel_batch(batch_id, tenant_id=tenant_id)
    if batch is None:
        raise ApiProblem.not_found("batch", batch_id)
    return batch


@router.get("/{batch_id}/records", response_model=PaginatedResponse[DatasetRecord])
def batch_records(
    batch_id: str,
    service: Service,
    tenant_id: Tenant,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=500)] = 50,
) -> PaginatedResponse[DatasetRecord]:
    records = service.batch_records(
        batch_id, page=page, per_page=per_page, tenant_id=tenant_id
    )
    if records is None:
        raise ApiProblem.not_found("batch", batch_id)
    return records


@router.get("/{batch_id}/export")
def export_batch(
    batch_id: str,
    service: Service,
    tenant_id: Tenant,
    format: Annotated[Literal["csv", "json"], Query()] = "csv",
    audit: Annotated[bool, Query()] = False,
) -> Response:
    rendered = service.export_batch(batch_id, fmt=format, audit=audit, tenant_id=tenant_id)
    if rendered is None:
        raise ApiProblem.not_found("batch", batch_id)
    return Response(
        content=rendered.content,
        media_type=rendered.media_type,
        headers={"Content-Disposition": f'attachment; filename="{rendered.filename}"'},
    )
