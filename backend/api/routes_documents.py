"""Document routes: the document itself and the mappings read off it.

Thin by rule. The distinction worth keeping is between an absent document and a document
with nothing mapped yet: the first is a 404, the second is `[]`. The service draws that
line by returning `None` only for absence, and this module does nothing but honour it --
collapsing the two would make an empty review drawer indistinguishable from a bad link.
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
from backend.engine.contracts import Document, Mapping

router = APIRouter(prefix="/api/documents", tags=["documents"])

Service = Annotated[PipelineService, Depends(get_pipeline_service)]
Tenant = Annotated[str, Depends(get_tenant_id)]


@router.get("/{document_id}", response_model=Document)
def get_document(document_id: str, service: Service, tenant_id: Tenant) -> Document:
    document = service.get_document(document_id, tenant_id=tenant_id)
    if document is None:
        raise ApiProblem.not_found("document", document_id)
    return document


@router.get("/{document_id}/mappings", response_model=list[Mapping])
def document_mappings(
    document_id: str, service: Service, tenant_id: Tenant
) -> list[Mapping]:
    mappings = service.document_mappings(document_id, tenant_id=tenant_id)
    if mappings is None:
        raise ApiProblem.not_found("document", document_id)
    return mappings
