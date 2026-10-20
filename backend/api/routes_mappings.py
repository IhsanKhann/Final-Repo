"""Mapping routes: the correction, the bulk accept, and the tray they come out of.

`PATCH /api/mappings/{id}` is the feedback loop surfacing in the UI, so the one thing this
module must not do is manufacture `learned`. The flag and its message come from the
service, which writes a precedent or does not; a route that defaulted `learned` to True
would turn the product's central claim into a decoration.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import (
    ApiProblem,
    PipelineService,
    get_pipeline_service,
    get_tenant_id,
)
from backend.engine.contracts import (
    BulkAcceptPayload,
    BulkAcceptResponse,
    MappingPatchPayload,
    MappingPatchResponse,
    ReviewQueueItem,
)

router = APIRouter(tags=["mappings"])

Service = Annotated[PipelineService, Depends(get_pipeline_service)]
Tenant = Annotated[str, Depends(get_tenant_id)]


@router.patch("/api/mappings/{mapping_id}", response_model=MappingPatchResponse)
def patch_mapping(
    mapping_id: str,
    payload: MappingPatchPayload,
    service: Service,
    tenant_id: Tenant,
) -> MappingPatchResponse:
    result = service.patch_mapping(mapping_id, payload, tenant_id=tenant_id)
    if result is None:
        raise ApiProblem.not_found("mapping", mapping_id)
    return result


@router.post("/api/mappings/bulk-accept", response_model=BulkAcceptResponse)
def bulk_accept(
    payload: BulkAcceptPayload, service: Service, tenant_id: Tenant
) -> BulkAcceptResponse:
    result = service.bulk_accept(payload, tenant_id=tenant_id)
    if result is None:
        raise ApiProblem.not_found("document", payload.document_id)
    return result


@router.get("/api/review-queue", response_model=list[ReviewQueueItem])
def review_queue(service: Service, tenant_id: Tenant) -> list[ReviewQueueItem]:
    return service.review_queue(tenant_id=tenant_id)
