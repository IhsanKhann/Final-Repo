"""Batch routes: list, create, read, cancel, events, records, export.

Thin by rule (README section 5): every handler parses, calls one service method and
serializes. The only thing resembling logic in here is turning a FastAPI `UploadFile` into
`deps.UploadedFile` and `None` into a typed 404 -- both of which exist precisely so that
no logic has to live below them in the engine or above them in the UI.

What these routes refuse to do:
  * They refuse to decide anything about a document. Stage, status, stats and events come
    from the service; a route that computed a stat would be a second source of truth.
  * They refuse to stream a traceback. A missing batch is `ApiProblem.not_found`.
  * They refuse to guess an export format. `format` is a Literal, so `?format=xml` is a
    422 from the framework rather than a half-written file.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from backend.api.deps import (
    ApiProblem,
    PipelineService,
    UploadedFile,
    get_pipeline_service,
    get_tenant_id,
)
from backend.engine.contracts import (
    AgentEvent,
    Batch,
    CreateBatchPayload,
    DatasetRecord,
    PaginatedResponse,
)

router = APIRouter(prefix="/api/batches", tags=["batches"])

Service = Annotated[PipelineService, Depends(get_pipeline_service)]
Tenant = Annotated[str, Depends(get_tenant_id)]


@router.get("", response_model=list[Batch])
def list_batches(service: Service, tenant_id: Tenant) -> list[Batch]:
    return service.list_batches(tenant_id=tenant_id)


async def _read_payload(
    request: Request,
    pack_id: str | None,
    url: str | None,
    files: list[UploadFile] | None,
) -> tuple[CreateBatchPayload, list[UploadedFile]]:
    """Accept the multipart form the UI sends, or a JSON body for curl and tests.

    `Frontend/src/api/client.ts` posts FormData with `pack_id`, optional `url` and repeated
    `files`. Supporting the JSON body too costs four lines and makes the endpoint drivable
    from a terminal, which is how it gets debugged on stage.
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
        return payload, []

    uploads: list[UploadedFile] = []
    for upload in files or []:
        content = await upload.read()
        uploads.append(
            UploadedFile(
                name=upload.filename or "unnamed",
                media_type=upload.content_type or "application/octet-stream",
                size_bytes=len(content),
                content=content,
            )
        )
    return CreateBatchPayload(pack_id=pack_id, url=url or None), uploads


@router.post("", response_model=Batch, status_code=201)
async def create_batch(
    request: Request,
    service: Service,
    tenant_id: Tenant,
    pack_id: Annotated[str | None, Form()] = None,
    url: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> Batch:
    payload, uploads = await _read_payload(request, pack_id, url, files)
    return service.create_batch(payload, uploads, tenant_id=tenant_id)


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
