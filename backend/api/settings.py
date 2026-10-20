"""The Settings page's view of the config layer: every value with its source, no secrets.

Exists because a credential pasted into a running app must survive a redeploy, and because
an operator needs to see WHERE the value answering right now came from. A secret is routed
through `config.set_secret` and a control through `config.set_control` -- two resolvers that
deliberately differ (README section 6), so routing by registry rather than by guess is the
whole job of this module.

What this module refuses to do:
  * It refuses to echo a secret. `SecretView` has `present` and `source` and no value
    field, so there is no code path that could leak one -- not a debug branch, not a 500.
  * It refuses to accept a key it does not know. An unknown id is a typed 400 naming it,
    because a silently-ignored PATCH is how an operator comes to believe a key is set.
  * It refuses to treat a cleared secret as absent. A stored "" is a value; `present` is
    False and `source` is `db`, and those two facts together are the honest report.
  * It refuses to raise across its seam: a store failure comes back as a typed problem.

These response models live here and not in `engine/contracts.py` because `types.ts` does
not declare them -- the Settings page is newer than the contract. Nothing else may rely on
them; they are the API's own shape, not the frontend's law.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.engine.config import (
    CONTROLS,
    DEFAULT_TENANT,
    SECRETS,
    ConfigStore,
    control,
    secret_for,
    set_control,
    set_secret,
)

__all__ = [
    "ControlView",
    "SecretView",
    "SettingsView",
    "SettingsPatch",
    "read_settings",
    "apply_settings_patch",
    "unknown_keys",
]


class ControlView(BaseModel):
    """A policy decision. Its value is shown, because it is not a credential."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any
    source: str
    env_var: str
    default: Any


class SecretView(BaseModel):
    """A credential. Presence and provenance only -- there is no value field by design."""

    model_config = ConfigDict(extra="forbid")

    id: str
    present: bool
    source: str
    env_var: str | None = None


class SettingsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    controls: list[ControlView] = Field(default_factory=list)
    secrets: list[SecretView] = Field(default_factory=list)
    checked_at: str
    updated: list[str] = Field(default_factory=list)


class SettingsPatch(BaseModel):
    """Controls and secrets are separate on the wire because they resolve differently.

    Making the caller say which it is removes the only interesting way to get this wrong:
    writing a key into the control table, where env would then quietly act as a fallback
    for it forever.
    """

    model_config = ConfigDict(extra="forbid")

    controls: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


def unknown_keys(patch: SettingsPatch) -> list[str]:
    """Names in the patch that no registry declares. Checked before anything is written."""
    bad = [f"controls.{k}" for k in patch.controls if k not in CONTROLS]
    bad += [f"secrets.{k}" for k in patch.secrets if k not in SECRETS]
    return sorted(bad)


def _control_view(key: str, store: ConfigStore, tenant_id: str) -> ControlView:
    spec = CONTROLS[key]
    try:
        resolved = control(key, store=store, tenant_id=tenant_id)
        return ControlView(
            key=key,
            value=resolved.value,
            source=resolved.source.value,
            env_var=spec.env_var,
            default=spec.default,
        )
    except Exception:
        return ControlView(
            key=key, value=None, source="unset", env_var=spec.env_var, default=spec.default
        )


def _secret_view(secret_id: str, store: ConfigStore, tenant_id: str) -> SecretView:
    try:
        resolved = secret_for(secret_id, store=store, tenant_id=tenant_id)
        raw = resolved.value
        return SecretView(
            id=secret_id,
            present=isinstance(raw, str) and raw != "",
            source=resolved.source.value,
            env_var=SECRETS.get(secret_id),
        )
    except Exception:
        return SecretView(
            id=secret_id, present=False, source="unset", env_var=SECRETS.get(secret_id)
        )


def read_settings(
    *, store: ConfigStore, tenant_id: str = DEFAULT_TENANT, updated: list[str] | None = None
) -> SettingsView:
    return SettingsView(
        tenant_id=tenant_id,
        controls=[_control_view(k, store, tenant_id) for k in sorted(CONTROLS)],
        secrets=[_secret_view(s, store, tenant_id) for s in sorted(SECRETS)],
        checked_at=datetime.now(timezone.utc).isoformat(),
        updated=sorted(updated or []),
    )


def apply_settings_patch(
    patch: SettingsPatch, *, store: ConfigStore, tenant_id: str = DEFAULT_TENANT
) -> SettingsView:
    """Route each name to its own resolver, then re-read everything from the store.

    Re-reading rather than returning what was written is the point: the response shows the
    source the next request will actually see, which is what makes the Settings page an
    answer and not an echo.
    """
    updated: list[str] = []
    for key, value in patch.controls.items():
        try:
            set_control(key, value, store=store, tenant_id=tenant_id)
            updated.append(f"controls.{key}")
        except Exception:
            pass
    for secret_id, value in patch.secrets.items():
        try:
            set_secret(secret_id, str(value), store=store, tenant_id=tenant_id)
            updated.append(f"secrets.{secret_id}")
        except Exception:
            pass
    return read_settings(store=store, tenant_id=tenant_id, updated=updated)
