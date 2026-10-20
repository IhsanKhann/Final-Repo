"""The routes that describe the system rather than a run: health, settings, packs,
insights and the home summary.

Health and settings are the two endpoints an operator judges the build by, so both are
composed in dedicated modules (`health.py`, `settings.py`) and these handlers stay what
every handler in this package is: parse, call, serialize.

What these routes refuse to do:
  * They refuse to let a secret out. `PATCH /api/settings` returns `SettingsView`, whose
    secret entries have `present` and `source` and no value field at all.
  * They refuse to accept a setting they cannot route. An unknown name is a typed 400
    before anything is written, because a PATCH that silently drops a key is how an
    operator comes to believe their credential is saved.
  * They refuse to answer health from a cache: `build_health` resolves on every request.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from backend.api.deps import (
    ApiProblem,
    PipelineService,
    get_config_store,
    get_pipeline_service,
    get_tenant_id,
)
from backend.api.health import build_health
from backend.api.settings import (
    SettingsPatch,
    SettingsView,
    apply_settings_patch,
    read_settings,
    unknown_keys,
)
from backend.engine.config import ConfigStore
from backend.engine.contracts import HealthStatus, HomeStats, Insights, SchemaPack

router = APIRouter(tags=["meta"])

Service = Annotated[PipelineService, Depends(get_pipeline_service)]
Tenant = Annotated[str, Depends(get_tenant_id)]
Store = Annotated[ConfigStore, Depends(get_config_store)]


# --- Health -------------------------------------------------------------------


@router.get("/api/health", response_model=HealthStatus)
def health(service: Service, store: Store, tenant_id: Tenant) -> HealthStatus:
    return build_health(
        store=store,
        pipeline_layers=service.health_layers(tenant_id=tenant_id),
        tenant_id=tenant_id,
    )


# --- Settings -----------------------------------------------------------------


@router.get("/api/settings", response_model=SettingsView)
def get_settings(store: Store, tenant_id: Tenant) -> SettingsView:
    return read_settings(store=store, tenant_id=tenant_id)


@router.patch("/api/settings", response_model=SettingsView)
def patch_settings(payload: SettingsPatch, store: Store, tenant_id: Tenant) -> SettingsView:
    bad = unknown_keys(payload)
    if bad:
        raise ApiProblem(
            400,
            "unknown setting(s): " + ", ".join(bad),
            code="unknown_setting",
            resource="settings",
        )
    return apply_settings_patch(payload, store=store, tenant_id=tenant_id)


# --- Home and insights --------------------------------------------------------


@router.get("/api/home/stats", response_model=HomeStats)
def home_stats(service: Service, tenant_id: Tenant) -> HomeStats:
    return service.home_stats(tenant_id=tenant_id)


@router.get("/api/insights", response_model=Insights)
def insights(service: Service, tenant_id: Tenant) -> Insights:
    return service.insights(tenant_id=tenant_id)


# --- Schema packs -------------------------------------------------------------


@router.get("/api/packs", response_model=list[SchemaPack])
def list_packs(service: Service, tenant_id: Tenant) -> list[SchemaPack]:
    return service.list_packs(tenant_id=tenant_id)


@router.get("/api/packs/{pack_id}", response_model=SchemaPack)
def get_pack(pack_id: str, service: Service, tenant_id: Tenant) -> SchemaPack:
    pack = service.get_pack(pack_id, tenant_id=tenant_id)
    if pack is None:
        raise ApiProblem.not_found("pack", pack_id)
    return pack


@router.put("/api/packs/{pack_id}", response_model=SchemaPack)
def put_pack(
    pack_id: str, patch: dict[str, Any], service: Service, tenant_id: Tenant
) -> SchemaPack:
    """The frontend sends `Partial<SchemaPack>`, so the body is a dict, not a SchemaPack.

    Validating it as a full SchemaPack here would reject every real edit from the UI; the
    service merges it onto the current pack and validates the result.
    """
    pack = service.put_pack(pack_id, patch, tenant_id=tenant_id)
    if pack is None:
        raise ApiProblem.not_found("pack", pack_id)
    return pack
