"""Two config resolvers that deliberately differ, and the store behind them.

Exists so that a credential pasted into the Settings page survives a redeploy, and so a
stale value left in a .env file can never answer for one that an operator has replaced.

What this module refuses to do:
  * It refuses to cache. No memo, no module singleton, no lru_cache on either resolver.
    The whole point is that the call after a write sees the new value.
  * It refuses to read .env on import. Only an entry point calls load_env(). A library
    that loads dotenv on import makes a key's presence depend on import order.
  * It refuses to let env act as a fallback for a secret. Env is a one-time SEED: the
    first resolution promotes it into the store and the store owns it from then on.
    Without that rule the key you paste dies, the stale one in .env quietly answers, and
    the Health page still says connected.
  * It refuses to treat an empty string as absent. A stored "" stops the chain exactly
    like a real value does, or clearing a key would be impossible.
"""

from __future__ import annotations

import os
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

DEFAULT_TENANT = "demo"


# --- Resolution outcome -------------------------------------------------------


class Source(str, Enum):
    """Where a resolved value actually came from. The Settings page shows this."""

    SESSION = "session"
    DB = "db"
    ENV_SEED = "env-seed"
    ENV = "env"
    DEFAULT = "default"
    LAST_KNOWN_GOOD = "last-known-good"
    UNSET = "unset"


class Resolved(BaseModel):
    """A value plus the provenance of the value. Frozen: a resolution is a fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    value: Any
    source: Source


# --- The control and secret registries ----------------------------------------
# A control is a policy decision, so chaining to env then a stated default is correct.
# A secret is not, which is why it is a separate table and a separate resolver.


class ControlSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    env_var: str
    default: Any
    cast: str = "str"  # str | int | float | bool


CONTROLS: dict[str, ControlSpec] = {
    c.key: c
    for c in [
        ControlSpec(key="provider", env_var="PROVIDER", default="openai"),
        ControlSpec(key="model", env_var="MODEL", default="gpt-4o-2024-11-20"),
        ControlSpec(key="vision_model", env_var="VISION_MODEL", default="gpt-4o-2024-11-20"),
        ControlSpec(key="temperature", env_var="TEMPERATURE", default=0.0, cast="float"),
        ControlSpec(key="max_tokens", env_var="MAX_TOKENS", default=1024, cast="int"),
        ControlSpec(key="timeout_s", env_var="TIMEOUT_S", default=30, cast="int"),
        ControlSpec(
            key="token_budget_per_doc",
            env_var="TOKEN_BUDGET_PER_DOC",
            default=40000,
            cast="int",
        ),
        ControlSpec(key="prompt_version", env_var="PROMPT_VERSION", default="v1"),
        # The two gate thresholds. Stated defaults, not calibrated values -- see gate.py.
        ControlSpec(
            key="gate_auto_threshold", env_var="GATE_AUTO_THRESHOLD", default=0.90, cast="float"
        ),
        ControlSpec(
            key="gate_review_threshold",
            env_var="GATE_REVIEW_THRESHOLD",
            default=0.60,
            cast="float",
        ),
        # Deliberately empty rather than naming a pack. A pack id is a domain noun, and
        # Law II keeps those out of the engine -- so an unset value means "the single pack
        # present in packs/", which the loader resolves by discovery.
        ControlSpec(key="active_pack_id", env_var="ACTIVE_PACK_ID", default=""),
        ControlSpec(
            key="async_page_threshold", env_var="ASYNC_PAGE_THRESHOLD", default=15, cast="int"
        ),
        ControlSpec(
            key="analyst_minutes_per_field",
            env_var="ANALYST_MINUTES_PER_FIELD",
            default=1.5,
            cast="float",
        ),
    ]
}

# secret id -> the env var that may SEED it exactly once.
SECRETS: dict[str, str] = {
    "openai_api_key": "OPENAI_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "google_api_key": "GOOGLE_API_KEY",
    "docai_processor_id": "DOCAI_PROCESSOR_ID",
}


def _cast(raw: Any, cast: str) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (int, float, bool)) and cast != "str":
        return raw
    s = str(raw)
    if s == "":
        # An explicit empty value is a value. Do not coerce it to 0 or False.
        return s
    if cast == "int":
        return int(float(s))
    if cast == "float":
        return float(s)
    if cast == "bool":
        return s.strip().lower() in {"1", "true", "yes", "on"}
    return s


# --- Secret storage cipher seam -----------------------------------------------


class SecretCipher(ABC):
    """Seam for at-rest protection of secrets. Cloud swaps in KMS behind this."""

    @abstractmethod
    def seal(self, plaintext: str) -> str: ...

    @abstractmethod
    def open(self, sealed: str) -> str: ...


class PassthroughCipher(SecretCipher):
    """Local development only. Stores the secret as given.

    Named honestly: this is NOT encryption at rest. The column is value_enc because a
    KMS-backed cipher drops in behind this interface without a migration, but with this
    implementation the local SQLite file holds readable keys. That file is gitignored and
    never leaves the machine; in cloud, a KMS cipher replaces this class.
    """

    def seal(self, plaintext: str) -> str:
        return plaintext

    def open(self, sealed: str) -> str:
        return sealed


# --- Store interface and its one local implementation -------------------------


class ConfigStore(ABC):
    """Interface written even though there is one implementation today.

    FirestoreStore drops in behind this for cloud (README section 6), selected by the
    CONFIG_STORE env var.
    """

    @abstractmethod
    def get_control(self, tenant_id: str, key: str) -> str | None: ...

    @abstractmethod
    def set_control(
        self, tenant_id: str, key: str, value: Any, source: Source, updated_by: str
    ) -> None: ...

    @abstractmethod
    def get_secret(self, tenant_id: str, secret_id: str) -> str | None: ...

    @abstractmethod
    def set_secret(
        self, tenant_id: str, secret_id: str, value: str, source: Source, updated_by: str
    ) -> None: ...

    @abstractmethod
    def list_controls(self, tenant_id: str) -> dict[str, str]: ...

    @abstractmethod
    def list_secret_ids(self, tenant_id: str) -> list[str]: ...

    @abstractmethod
    def get_last_known_good(self, tenant_id: str, key: str) -> str | None: ...

    @abstractmethod
    def record_last_known_good(self, tenant_id: str, key: str, value: Any) -> None: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".data" / "config.db"


class SqliteStore(ConfigStore):
    """The local store. One connection per call: no singleton to go stale."""

    def __init__(
        self, db_path: str | Path | None = None, cipher: SecretCipher | None = None
    ) -> None:
        self.db_path = Path(db_path or os.environ.get("CONFIG_DB_PATH") or _default_db_path())
        self.cipher = cipher or PassthroughCipher()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS config (
                    tenant_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
                    source TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, key)
                );
                CREATE TABLE IF NOT EXISTS secrets (
                    tenant_id TEXT NOT NULL, id TEXT NOT NULL, value_enc TEXT,
                    source TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, id)
                );
                CREATE TABLE IF NOT EXISTS last_known_good (
                    tenant_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
                    updated_at TEXT NOT NULL, PRIMARY KEY (tenant_id, key)
                );
                """
            )

    def get_control(self, tenant_id: str, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM config WHERE tenant_id=? AND key=?", (tenant_id, key)
            ).fetchone()
        return None if row is None else row["value"]

    def set_control(
        self, tenant_id: str, key: str, value: Any, source: Source, updated_by: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO config (tenant_id,key,value,source,updated_by,updated_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(tenant_id,key) DO UPDATE SET value=excluded.value, "
                "source=excluded.source, updated_by=excluded.updated_by, "
                "updated_at=excluded.updated_at",
                (
                    tenant_id,
                    key,
                    "" if value is None else str(value),
                    source.value,
                    updated_by,
                    _now(),
                ),
            )

    def get_secret(self, tenant_id: str, secret_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_enc FROM secrets WHERE tenant_id=? AND id=?", (tenant_id, secret_id)
            ).fetchone()
        if row is None:
            return None
        return self.cipher.open(row["value_enc"] or "")

    def set_secret(
        self, tenant_id: str, secret_id: str, value: str, source: Source, updated_by: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO secrets (tenant_id,id,value_enc,source,updated_by,updated_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(tenant_id,id) DO UPDATE SET value_enc=excluded.value_enc, "
                "source=excluded.source, updated_by=excluded.updated_by, "
                "updated_at=excluded.updated_at",
                (tenant_id, secret_id, self.cipher.seal(value), source.value, updated_by, _now()),
            )

    def list_controls(self, tenant_id: str) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM config WHERE tenant_id=?", (tenant_id,)
            ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def list_secret_ids(self, tenant_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM secrets WHERE tenant_id=?", (tenant_id,)
            ).fetchall()
        return [r["id"] for r in rows]

    def get_last_known_good(self, tenant_id: str, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM last_known_good WHERE tenant_id=? AND key=?", (tenant_id, key)
            ).fetchone()
        return None if row is None else row["value"]

    def record_last_known_good(self, tenant_id: str, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO last_known_good (tenant_id,key,value,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(tenant_id,key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (tenant_id, key, "" if value is None else str(value), _now()),
            )


def make_store() -> ConfigStore:
    """Pick the store by one env var, per README section 6."""
    kind = (os.environ.get("CONFIG_STORE") or "sqlite").strip().lower()
    if kind == "sqlite":
        return SqliteStore()
    if kind == "firestore":
        raise NotImplementedError(
            "FirestoreStore belongs to the infra lane. Set CONFIG_STORE=sqlite to run locally."
        )
    raise ValueError(f"unknown CONFIG_STORE {kind!r}; expected 'sqlite' or 'firestore'")


# --- Entry-point-only dotenv loading ------------------------------------------


def load_env(path: str | Path | None = None) -> bool:
    """Load .env into os.environ. ONLY entry points may call this.

    A library module that loads dotenv on import makes a key's presence depend on import
    order. tests/test_env_is_loaded.py asserts every entry point calls this, because the
    opposite failure is worse and silent: a valid key sits in a file nothing reads and
    every agent reports no-key.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    target = Path(path) if path else Path(__file__).resolve().parents[2] / ".env"
    return bool(load_dotenv(target, override=False))


# --- The two resolvers --------------------------------------------------------


def control(
    key: str,
    *,
    store: ConfigStore | None = None,
    session: dict[str, Any] | None = None,
    tenant_id: str = DEFAULT_TENANT,
) -> Resolved:
    """session -> db -> env -> default. Chains freely; a control is a policy decision.

    No cache by design. Falls back to last-known-good only if the store itself is
    unreachable -- and only for controls, never for secrets, because last-known-good on a
    secret would resurrect a key the operator had just revoked.
    """
    spec = CONTROLS.get(key)
    cast = spec.cast if spec else "str"

    if session and key in session:
        return Resolved(key=key, value=_cast(session[key], cast), source=Source.SESSION)

    store = store or make_store()
    try:
        stored = store.get_control(tenant_id, key)
    except Exception:
        lkg = None
        try:
            lkg = store.get_last_known_good(tenant_id, key)
        except Exception:
            pass
        if lkg is not None:
            return Resolved(key=key, value=_cast(lkg, cast), source=Source.LAST_KNOWN_GOOD)
        stored = None

    if stored is not None:
        # An explicit empty value is a value. "" stops the chain.
        try:
            store.record_last_known_good(tenant_id, key, stored)
        except Exception:
            pass
        return Resolved(key=key, value=_cast(stored, cast), source=Source.DB)

    if spec is None:
        return Resolved(key=key, value=None, source=Source.UNSET)

    env_raw = os.environ.get(spec.env_var)
    if env_raw is not None:
        return Resolved(key=key, value=_cast(env_raw, cast), source=Source.ENV)

    return Resolved(key=key, value=spec.default, source=Source.DEFAULT)


def secret_for(
    secret_id: str,
    *,
    store: ConfigStore | None = None,
    session: dict[str, Any] | None = None,
    tenant_id: str = DEFAULT_TENANT,
    updated_by: str = "env-seed",
) -> Resolved:
    """session -> db -> env SEED (once) -> then STOPS. Never reads env again.

    The promotion is the whole mechanism: the first resolution with nothing stored writes
    the env value into the store labelled env-seed, and after that the store owns it.
    There is no DEFAULT branch and no LAST_KNOWN_GOOD branch here, on purpose.
    """
    if session and secret_id in session:
        return Resolved(key=secret_id, value=str(session[secret_id]), source=Source.SESSION)

    store = store or make_store()
    stored = store.get_secret(tenant_id, secret_id)
    if stored is not None:
        # Including "" -- a cleared secret must stay cleared.
        return Resolved(key=secret_id, value=stored, source=Source.DB)

    env_var = SECRETS.get(secret_id)
    if env_var:
        env_raw = os.environ.get(env_var)
        if env_raw is not None:
            store.set_secret(tenant_id, secret_id, env_raw, Source.ENV_SEED, updated_by)
            return Resolved(key=secret_id, value=env_raw, source=Source.ENV_SEED)

    return Resolved(key=secret_id, value=None, source=Source.UNSET)


def set_control(
    key: str,
    value: Any,
    *,
    store: ConfigStore | None = None,
    tenant_id: str = DEFAULT_TENANT,
    updated_by: str = "settings-page",
) -> Resolved:
    store = store or make_store()
    store.set_control(tenant_id, key, value, Source.DB, updated_by)
    return control(key, store=store, tenant_id=tenant_id)


def set_secret(
    secret_id: str,
    value: str,
    *,
    store: ConfigStore | None = None,
    tenant_id: str = DEFAULT_TENANT,
    updated_by: str = "settings-page",
) -> Resolved:
    store = store or make_store()
    store.set_secret(tenant_id, secret_id, value, Source.DB, updated_by)
    return secret_for(secret_id, store=store, tenant_id=tenant_id)
