"""The routes that describe the system rather than a run: health, settings, providers,
model catalogues, packs, insights and the home summary.

Health and settings are the two endpoints an operator judges the build by, so both are
composed in dedicated modules (`health.py`, `settings.py`) and these handlers stay what
every handler in this package is: parse, call, serialize.

What these routes refuse to do:
  * They refuse to let a secret out. `PATCH /api/settings` returns `SettingsView`, whose
    secret entries have `present` and `source` and no value field at all. `/api/providers`
    reports a key through that same `SecretView` rather than a field of its own, so there
    is no second type that could ever grow a value.
  * They refuse to accept a setting they cannot route. An unknown name is a typed 400
    before anything is written, because a PATCH that silently drops a key is how an
    operator comes to believe their credential is saved. An unknown provider id is the
    same 400 for the same reason.
  * They refuse to answer health from a cache: `build_health` resolves on every request.
  * They refuse to put a socket in `intelligence/providers.py`. The catalogue fetch goes
    through an injected transport, declared here and resolved by a dependency, so a test
    replays a recorded catalogue with no key and no wifi.
  * They refuse to flatten a provider failure. `/api/models` answers 200 with a named
    state from the same six `intelligence` uses -- `model-unavailable` keeps its own name,
    because a listed model is not a callable one and merging it into `bad-key` would blame
    the operator's credential for the provider's cutoff.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Mapping, Protocol, runtime_checkable

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.api.deps import (
    ApiProblem,
    PipelineService,
    get_config_store,
    get_pipeline_service,
    get_tenant_id,
)
from backend.api.health import build_health
from backend.api.settings import (
    SecretView,
    SettingsPatch,
    SettingsView,
    apply_settings_patch,
    read_settings,
    unknown_keys,
)
from backend.engine.config import SECRETS, ConfigStore, control, secret_for
from backend.engine.contracts import (
    HealthStatus,
    HomeStats,
    Insights,
    SchemaPack,
    Unavailable,
)
from backend.intelligence import providers as prov
from backend.intelligence.base import (
    TransportReply,
    TransportTimeout,
    TransportUnreachable,
)

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


# --- Providers and their model catalogues -------------------------------------
# Bring-your-own-model is a product claim (README section 6): a customer pastes their own
# key, picks any model that key reaches, and two models can be A/B'd on the same documents
# without a code change. These two endpoints are what makes that claim operable, and the
# response models live here for the same reason `settings.py`'s do -- `types.ts` does not
# declare them, so they are the API's own shape and nothing else may rely on them.


class ProviderView(BaseModel):
    """One row of the providers table as a picker sees it. There is no key in it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    dialect: str
    #: A model we have actually called, not one scraped from a catalogue.
    default_model: str
    #: False for the bring-your-own-model row, whose catalogue answers unauthenticated --
    #: which is why the picker can populate before anyone has signed in.
    models_need_key: bool
    #: The id in the secret registry that holds this row's key. A name, never a value; it
    #: is what lets the Settings page link a provider to the field that configures it.
    secret_id: str
    #: Presence and provenance, in the Settings page's own type. `SecretView` has no value
    #: field by design, so this cannot leak a key -- not in a debug branch, not in a 500.
    key: SecretView


class ModelView(BaseModel):
    """One entry from a provider's catalogue. Listed, which is not the same as callable."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    context_length: int | None = None


class ModelsView(BaseModel):
    """A catalogue, or the named reason there is not one. Never an exception.

    `unavailable` is `intelligence`'s own `Unavailable`, so the six states the Health
    banner already renders are the six states this endpoint can report. A seventh name
    invented here would reach the UI as a blank reason.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    models: list[ModelView] = Field(default_factory=list)
    default_model: str
    models_need_key: bool
    key: SecretView
    checked_at: str
    unavailable: Unavailable | None = None


@runtime_checkable
class CatalogueTransport(Protocol):
    """Anything that can GET JSON and come back with a status. Injected, never built.

    The sibling of `intelligence.base.Transport`, which declares `post` only because a
    completion is the only thing the seam below it sends. Same contract otherwise: the
    reply is `TransportReply`, a timeout and an unreachable host are the two named
    exceptions, and a test supplies this instead of a socket.
    """

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout_s: float
    ) -> TransportReply: ...


def httpx_catalogue_transport() -> CatalogueTransport | None:
    """The one real transport. Imports httpx inside the body, like `httpx_transport()`.

    None rather than a raise when httpx is absent: a missing HTTP library is one of the
    named states below, not a 500 on an endpoint whose other half is local data.
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover - environment-dependent
        return None

    class _HttpxCatalogue:
        def get(
            self, url: str, *, headers: Mapping[str, str], timeout_s: float
        ) -> TransportReply:
            try:
                response = httpx.get(url, headers=dict(headers), timeout=timeout_s)
            except httpx.TimeoutException as exc:
                raise TransportTimeout(str(exc)) from exc
            except httpx.TransportError as exc:
                raise TransportUnreachable(str(exc)) from exc
            try:
                payload = response.json()
            except ValueError:
                payload = None
            return TransportReply(
                status=response.status_code,
                payload=payload if isinstance(payload, dict) else None,
                text=response.text,
            )

    return _HttpxCatalogue()


def get_catalogue_transport() -> CatalogueTransport | None:
    """A dependency, so a test overrides it with a recorded reply and no wifi."""
    return httpx_catalogue_transport()


Catalogue = Annotated[CatalogueTransport | None, Depends(get_catalogue_transport)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key_for(
    provider: prov.Provider, store: ConfigStore, tenant_id: str
) -> tuple[str | None, SecretView]:
    """Resolve the row's key and the view of it. The value goes to the transport only."""
    try:
        resolved = secret_for(provider.secret_id, store=store, tenant_id=tenant_id)
        raw = resolved.value
        source = resolved.source.value
    except Exception:
        raw, source = None, "unset"
    present = isinstance(raw, str) and raw != ""
    view = SecretView(
        id=provider.secret_id,
        present=present,
        source=source,
        env_var=SECRETS.get(provider.secret_id),
    )
    return (raw if present else None), view


def _models_from_payload(payload: Mapping[str, Any] | None) -> list[ModelView]:
    """Read a catalogue body. Pure, and tolerant of both dialects' spelling.

    Both answer with a `data` array of objects carrying an `id`; the human label is `name`
    on one and `display_name` on the other, so both are read and neither is required. An
    entry with no id is skipped rather than guessed at -- an unnamed model in a picker is
    a 404 waiting to happen.
    """
    body = payload or {}
    rows = body.get("data")
    if not isinstance(rows, list):
        rows = body.get("models")
    models: list[ModelView] = []
    for row in rows or []:
        if isinstance(row, str):
            models.append(ModelView(id=row))
            continue
        if not isinstance(row, Mapping):
            continue
        model_id = row.get("id") or row.get("name")
        if not model_id:
            continue
        label = row.get("display_name") or row.get("name")
        context = row.get("context_length") or row.get("context_window")
        models.append(
            ModelView(
                id=str(model_id),
                label=str(label) if label else None,
                context_length=int(context) if isinstance(context, (int, float)) else None,
            )
        )
    return sorted(models, key=lambda m: m.id)


@router.get("/api/providers", response_model=list[ProviderView])
def list_providers(store: Store, tenant_id: Tenant) -> list[ProviderView]:
    """The four rows as data. Local, so this answers with no key and no network."""
    views: list[ProviderView] = []
    for provider_id in sorted(prov.PROVIDERS):
        provider = prov.PROVIDERS[provider_id]
        _, key_view = _key_for(provider, store, tenant_id)
        views.append(
            ProviderView(
                id=provider.id,
                dialect=provider.dialect.value,
                default_model=provider.default_model,
                models_need_key=provider.models_need_key,
                secret_id=provider.secret_id,
                key=key_view,
            )
        )
    return views


@router.get("/api/models", response_model=ModelsView)
def list_models(
    store: Store,
    tenant_id: Tenant,
    transport: Catalogue,
    provider: Annotated[str, Query(min_length=1)],
) -> ModelsView:
    """The callable model list for one provider, or the named reason there is not one.

    200 with `unavailable` set, not a 4xx or 5xx: the provider list beside it is local
    data and still correct, and the picker has to be able to say WHY it is empty. The one
    4xx here is an id no row declares, which is a caller mistake rather than a provider
    failure -- the same reasoning as an unknown setting name.
    """
    row = prov.provider_for(provider)
    if row is None:
        raise ApiProblem(
            400,
            f"unknown provider {provider!r}; known: {sorted(prov.PROVIDERS)}",
            code="unknown_provider",
            resource="provider",
            id=provider,
        )

    key, key_view = _key_for(row, store, tenant_id)
    view = ModelsView(
        provider=row.id,
        default_model=row.default_model,
        models_need_key=row.models_need_key,
        key=key_view,
        checked_at=_now(),
    )

    def failed(reason: str, detail: str) -> ModelsView:
        return view.model_copy(
            update={"unavailable": Unavailable(reason=reason, detail=detail)}
        )

    preflight = prov.preflight(row, key)
    if preflight is not None:
        return failed(
            preflight.value,
            f"{row.id} does not answer its catalogue without a key; none resolved from "
            "the config store",
        )
    if transport is None:
        return failed("provider-down", "no transport injected; no catalogue can be read")

    try:
        url = prov.base_url_for(row.id) + row.models_path
    except Exception as exc:
        # A base_url with an unfilled placeholder. Named, with the message, rather than a
        # URL that would 404 at 3am.
        return failed("provider-down", f"{type(exc).__name__}: {exc}")

    # An empty `Authorization: Bearer ` is not the same request as no header at all, and
    # the row that answers unauthenticated is the one we would be breaking. So with no key
    # resolved, the auth header is omitted rather than sent blank.
    headers = prov.auth_headers(row, key) if key else {"content-type": "application/json"}
    timeout_s = float(control("timeout_s", store=store, tenant_id=tenant_id).value or 30)

    try:
        reply = transport.get(url, headers=headers, timeout_s=timeout_s)
    except TransportTimeout as exc:
        return failed("timeout", str(exc) or f"{timeout_s}s")
    except TransportUnreachable as exc:
        return failed("provider-down", str(exc))
    except Exception as exc:
        return failed("provider-down", f"{type(exc).__name__}: {exc}")

    failure = prov.classify_http_status(reply.status, reply.payload or reply.text)
    if failure is not None:
        return failed(
            failure.value,
            f"HTTP {reply.status} from {row.id}: "
            f"{(reply.text or str(reply.payload or ''))[:400]}",
        )

    models = _models_from_payload(reply.payload)
    if not models:
        return failed(
            "provider-down",
            f"{row.id} answered HTTP {reply.status} with no model list in the body",
        )
    return view.model_copy(update={"models": models})


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
