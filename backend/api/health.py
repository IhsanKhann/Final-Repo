"""Live provider state, with the provenance of every value and the value of no secret.

Exists because "is it connected?" is the question a demo dies on. The Health page must say,
per layer, whether a key is present and WHERE the answer came from -- session, db, env-seed,
default or unset -- so that a key pasted into Settings and a stale one left in a .env file
can never look the same. It calls `config.control` / `config.secret_for` on every request.

What this module refuses to do:
  * It refuses to return a secret's value. Only `present` and `source`. There is a test
    that asserts the response body does not contain the configured key.
  * It refuses to cache. A health check that answers from a cache is answering about the
    past, which is the one thing it must not do.
  * It refuses to raise. Every probe is wrapped; an unreachable store becomes a `down`
    layer with a reason, because README section 7 promises the app still starts and serves.
  * It refuses to report `ok` when nothing can be inferred. With no key configured the
    overall status is `degraded` and the reason is in a layer the page shows.

One constraint worth naming: `types.ts` is law and its `HealthLayer` has no `source`
field, so the provenance travels in `message` as a trailing `| source=<...>`. Adding a
field would mean editing the contract, which this repo does not do.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from backend.engine.config import (
    CONTROLS,
    DEFAULT_TENANT,
    SECRETS,
    ConfigStore,
    control,
    secret_for,
)
from backend.engine.contracts import HealthLayer, HealthStatus

__all__ = ["build_health", "PROVIDER_SECRETS"]

#: The secrets that can make inference possible. `docai_processor_id` is deliberately not
#: one of them: it enables scanned PDFs, it does not enable a model call.
PROVIDER_SECRETS: tuple[str, ...] = (
    "openai_api_key",
    "openrouter_api_key",
    "anthropic_api_key",
    "google_api_key",
)

_SECRET_LABELS = {
    "openai_api_key": "OpenAI key",
    "openrouter_api_key": "OpenRouter key",
    "anthropic_api_key": "Anthropic key",
    "google_api_key": "Google key",
    "docai_processor_id": "Document AI processor id",
}

_WORST = {"ok": 0, "degraded": 1, "down": 2}


def _label(secret_id: str) -> str:
    return _SECRET_LABELS.get(secret_id, secret_id.replace("_", " "))


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _store_layer(store: ConfigStore) -> HealthLayer:
    started = perf_counter()
    try:
        count = len(store.list_controls(DEFAULT_TENANT))
        return HealthLayer(
            name="Config store",
            status="ok",
            latency_ms=_ms(started),
            message=f"{count} stored control(s) | source=env:CONFIG_STORE",
        )
    except Exception as exc:
        return HealthLayer(
            name="Config store",
            status="down",
            latency_ms=_ms(started),
            message=f"unreachable: {type(exc).__name__} | source=env:CONFIG_STORE",
        )


def _secret_layer(secret_id: str, store: ConfigStore, tenant_id: str) -> HealthLayer:
    """Presence and provenance. The value never leaves this function."""
    started = perf_counter()
    try:
        resolved = secret_for(secret_id, store=store, tenant_id=tenant_id)
    except Exception as exc:
        return HealthLayer(
            name=_label(secret_id),
            status="down",
            latency_ms=_ms(started),
            message=f"could not resolve: {type(exc).__name__} | source=unset",
        )
    raw = resolved.value
    # An explicit empty value is a value, and it is an absent key. A stored "" means the
    # operator cleared it; reporting that as present is how a demo ends up calling a
    # provider with no credential and blaming the network.
    present = isinstance(raw, str) and raw != ""
    note = "key present" if present else ("key explicitly cleared" if raw == "" else "no key")
    return HealthLayer(
        name=_label(secret_id),
        status="ok" if present else "degraded",
        latency_ms=_ms(started),
        message=f"{note} | source={resolved.source.value}",
    )


def _control_layer(key: str, store: ConfigStore, tenant_id: str) -> HealthLayer:
    """A control is a policy decision, so its value is shown -- with its source."""
    started = perf_counter()
    try:
        resolved = control(key, store=store, tenant_id=tenant_id)
    except Exception as exc:
        return HealthLayer(
            name=key,
            status="down",
            latency_ms=_ms(started),
            message=f"could not resolve: {type(exc).__name__} | source=unset",
        )
    return HealthLayer(
        name=key,
        status="ok",
        latency_ms=_ms(started),
        message=f"{resolved.value} | source={resolved.source.value}",
    )


def build_health(
    *,
    store: ConfigStore,
    pipeline_layers: list[HealthLayer],
    tenant_id: str = DEFAULT_TENANT,
) -> HealthStatus:
    """Compose the live answer. Called on every request; nothing here is memoised.

    `pipeline_layers` comes from the PipelineService, which may speak for the pack and the
    engine but NOT for key presence -- that is read here, from config.py, so no service can
    misreport whether a credential exists.
    """
    started = perf_counter()
    layers: list[HealthLayer] = [
        HealthLayer(name="API", status="ok", latency_ms=0, message="serving | source=default"),
        _store_layer(store),
    ]

    secret_layers = [_secret_layer(sid, store, tenant_id) for sid in sorted(SECRETS)]
    layers.extend(secret_layers)

    any_provider_key = any(
        layer.status == "ok"
        for sid, layer in zip(sorted(SECRETS), secret_layers)
        if sid in PROVIDER_SECRETS
    )
    layers.append(
        HealthLayer(
            name="Inference",
            status="ok" if any_provider_key else "degraded",
            latency_ms=None,
            message=(
                "a provider key is configured | source=see key layers"
                if any_provider_key
                else (
                    "degraded: no provider key is configured, so the mapper, extractor and "
                    "verifier return Unavailable and every unresolved field queues for "
                    "review. Precedent matches still resolve. | source=unset"
                )
            ),
        )
    )

    layers.extend(_control_layer(key, store, tenant_id) for key in sorted(CONTROLS))
    layers.extend(pipeline_layers)

    overall = max(layers, key=lambda layer: _WORST[layer.status]).status
    layers[0] = layers[0].model_copy(update={"latency_ms": _ms(started)})
    return HealthStatus(
        overall=overall,
        layers=layers,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
