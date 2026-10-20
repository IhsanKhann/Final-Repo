"""The cloud ConfigStore. Why it exists, and why the deployment is wrong without it.

Cloud Run containers have an ephemeral filesystem. `SqliteStore` writes to
`backend/.data/config.db`, which lives inside the container image's writable layer --
so on Cloud Run every new revision starts with an EMPTY config store. The key an
operator set on the Settings page would vanish on the next deploy.

That is not a degradation. It is the exact inverse of the claim this project makes on
stage ("change the key, redeploy, it survives"), and it would be false in precisely the
environment where we demonstrate it. So `CONFIG_STORE=firestore` is not an optimisation
for cloud; it is what makes the deployed system behave the way the local one does.

Document layout, per README section 6:

    tenants/{tenant_id}/config/{key}      {value, source, updated_by, updated_at}
    tenants/{tenant_id}/secrets/{id}      {value, source, updated_by, updated_at}
    tenants/{tenant_id}/lkg/{key}         {value, updated_at}

Two deliberate choices:

* **No caching, no client singleton beyond the lazy connection.** `controls.py`'s whole
  point is that the next call sees the new value; a memo here would reintroduce exactly
  the staleness the two-resolver rule exists to prevent.
* **Last-known-good is a separate collection, not a field.** It applies to controls only
  and never to secrets -- mixing them in one document invites a future `set_secret` from
  writing a credential into the recovery path, which would resurrect a revoked key.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.engine.config import ConfigStore, Source


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FirestoreStore(ConfigStore):
    """Config and secrets in Firestore, keyed by tenant.

    The google-cloud-firestore import is deferred to construction so that importing this
    module -- which `make_store` does on every start, whatever the backend -- never
    requires the dependency or touches the network. `tests/test_providers.py` asserts
    that nothing under intelligence/ performs IO at import time; the same discipline
    applies here.
    """

    def __init__(self, project_id: str | None = None, database: str | None = None) -> None:
        from google.cloud import firestore  # deferred on purpose

        kwargs: dict[str, Any] = {}
        if project_id:
            kwargs["project"] = project_id
        if database:
            kwargs["database"] = database
        self._db = firestore.Client(**kwargs)

    # --- paths ---------------------------------------------------------------

    def _doc(self, tenant_id: str, collection: str, key: str):
        return (
            self._db.collection("tenants")
            .document(tenant_id)
            .collection(collection)
            .document(key)
        )

    @staticmethod
    def _value_of(snapshot) -> str | None:
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        value = data.get("value")
        # An explicitly stored "" is a value and must stop the resolver chain, exactly as
        # in SqliteStore. Returning None here would let env re-seed a cleared key, which
        # makes "no key configured" unsayable.
        return "" if value is None else str(value)

    # --- controls ------------------------------------------------------------

    def get_control(self, tenant_id: str, key: str) -> str | None:
        return self._value_of(self._doc(tenant_id, "config", key).get())

    def set_control(
        self, tenant_id: str, key: str, value: Any, source: Source, updated_by: str
    ) -> None:
        self._doc(tenant_id, "config", key).set(
            {
                "value": "" if value is None else str(value),
                "source": source.value if isinstance(source, Source) else str(source),
                "updated_by": updated_by,
                "updated_at": _now(),
            }
        )

    def list_controls(self, tenant_id: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for snap in (
            self._db.collection("tenants").document(tenant_id).collection("config").stream()
        ):
            value = self._value_of(snap)
            if value is not None:
                out[snap.id] = value
        return out

    # --- secrets -------------------------------------------------------------

    def get_secret(self, tenant_id: str, secret_id: str) -> str | None:
        return self._value_of(self._doc(tenant_id, "secrets", secret_id).get())

    def set_secret(
        self, tenant_id: str, secret_id: str, value: str, source: Source, updated_by: str
    ) -> None:
        self._doc(tenant_id, "secrets", secret_id).set(
            {
                "value": "" if value is None else str(value),
                "source": source.value if isinstance(source, Source) else str(source),
                "updated_by": updated_by,
                "updated_at": _now(),
            }
        )

    def list_secret_ids(self, tenant_id: str) -> list[str]:
        return sorted(
            snap.id
            for snap in self._db.collection("tenants")
            .document(tenant_id)
            .collection("secrets")
            .stream()
        )

    # --- last known good (controls only) --------------------------------------

    def get_last_known_good(self, tenant_id: str, key: str) -> str | None:
        return self._value_of(self._doc(tenant_id, "lkg", key).get())

    def record_last_known_good(self, tenant_id: str, key: str, value: Any) -> None:
        self._doc(tenant_id, "lkg", key).set(
            {"value": "" if value is None else str(value), "updated_at": _now()}
        )
