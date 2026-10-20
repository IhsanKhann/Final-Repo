"""One evidence record per cell, append only. This is the answer to "how do we know?"

Exists so that clicking a cell can show the page it came from, the rule that fired, the
model and prompt version behind it, and who approved it -- and so that none of that can be
quietly revised later. A re-run does not overwrite a cell's history; it adds a version.

Each entry carries the hash of the entry before it. That makes the chain tamper-evident
rather than merely append-only by convention: a row edited in place breaks verify_chain(),
which is what lets the audit export be a claim rather than a hope.

reviewed_by and approved_by both exist from the first hour even though nothing fills
approved_by yet. Maker-checker is deferred, not designed out: adding it must cost a gate
rule reading pack materiality, not a schema migration (CLAUDE.md 6b).

What this module refuses to do:
  * It refuses to update or delete. There is no UPDATE and no DELETE in this file.
  * It refuses to call a model. It is in the engine (Law I).
  * It refuses to interpret what it stores. Field names and units are opaque (Law II).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

GENESIS_HASH = "0" * 64


class LedgerEntry(BaseModel):
    """One cell, at one version, with everything needed to defend the number in it."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = "demo"
    run_id: str
    document_id: str
    mapping_id: str
    source_label: str
    target_field: str
    raw_value: str
    raw_unit: str | None = None
    value: str
    unit: str | None = None
    status: str
    confidence: float
    authority: str | None = None
    conversion_rule_id: str | None = None
    formula_text: str | None = None
    source_location: dict[str, Any] | None = None
    #: The five controlled variables, recorded per cell so a round comparison can prove
    #: nothing moved underneath it.
    pack_id: str | None = None
    pack_version: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    #: What was sent, not what was intended -- see RoundReport.sampling.
    sampling: str | None = None
    reason: str | None = None
    reviewed_by: str | None = None
    approved_by: str | None = None

    # Filled by the ledger on append; never supplied by a caller.
    version: int = 0
    prev_hash: str = GENESIS_HASH
    entry_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _canonical(entry: LedgerEntry) -> bytes:
    """Stable serialization for hashing: sorted keys, no whitespace, hashes excluded."""
    payload = entry.model_dump(exclude={"entry_hash"}, mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_hash(entry: LedgerEntry) -> str:
    return hashlib.sha256(_canonical(entry)).hexdigest()


class Ledger(ABC):
    """Interface written though there is one implementation; BigQuery swaps in behind it."""

    @abstractmethod
    def append(self, entry: LedgerEntry) -> LedgerEntry: ...

    @abstractmethod
    def history(self, document_id: str, target_field: str, tenant_id: str = "demo") -> list[LedgerEntry]: ...

    @abstractmethod
    def latest_for_document(self, document_id: str, tenant_id: str = "demo") -> list[LedgerEntry]: ...

    @abstractmethod
    def verify_chain(self, tenant_id: str = "demo") -> tuple[bool, str | None]: ...


def _default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".data" / "ledger.db"


class SqliteLedger(Ledger):
    """Append-only ledger over SQLite. One connection per call."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or _default_db_path())
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
                CREATE TABLE IF NOT EXISTS ledger (
                    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id     TEXT NOT NULL,
                    run_id        TEXT NOT NULL,
                    document_id   TEXT NOT NULL,
                    mapping_id    TEXT NOT NULL,
                    source_label  TEXT NOT NULL,
                    target_field  TEXT NOT NULL,
                    version       INTEGER NOT NULL,
                    payload       TEXT NOT NULL,
                    prev_hash     TEXT NOT NULL,
                    entry_hash    TEXT NOT NULL,
                    created_at    TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ledger_cell
                    ON ledger (tenant_id, document_id, target_field, version);
                CREATE INDEX IF NOT EXISTS ledger_run ON ledger (tenant_id, run_id);
                """
            )

    def _tip_hash(self, conn: sqlite3.Connection, tenant_id: str) -> str:
        row = conn.execute(
            "SELECT entry_hash FROM ledger WHERE tenant_id=? ORDER BY seq DESC LIMIT 1",
            (tenant_id,),
        ).fetchone()
        return GENESIS_HASH if row is None else row["entry_hash"]

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        """Add one version of one cell. Never replaces an earlier version."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(version) AS v FROM ledger "
                "WHERE tenant_id=? AND document_id=? AND target_field=?",
                (entry.tenant_id, entry.document_id, entry.target_field),
            ).fetchone()
            next_version = 1 if row is None or row["v"] is None else int(row["v"]) + 1

            sealed = entry.model_copy(
                update={
                    "version": next_version,
                    "prev_hash": self._tip_hash(conn, entry.tenant_id),
                }
            )
            sealed = sealed.model_copy(update={"entry_hash": compute_hash(sealed)})

            conn.execute(
                "INSERT INTO ledger (tenant_id,run_id,document_id,mapping_id,source_label,"
                "target_field,version,payload,prev_hash,entry_hash,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sealed.tenant_id,
                    sealed.run_id,
                    sealed.document_id,
                    sealed.mapping_id,
                    sealed.source_label,
                    sealed.target_field,
                    sealed.version,
                    sealed.model_dump_json(),
                    sealed.prev_hash,
                    sealed.entry_hash,
                    sealed.created_at,
                ),
            )
        return sealed

    def history(
        self, document_id: str, target_field: str, tenant_id: str = "demo"
    ) -> list[LedgerEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM ledger WHERE tenant_id=? AND document_id=? AND "
                "target_field=? ORDER BY version ASC",
                (tenant_id, document_id, target_field),
            ).fetchall()
        return [LedgerEntry.model_validate_json(r["payload"]) for r in rows]

    def latest_for_document(self, document_id: str, tenant_id: str = "demo") -> list[LedgerEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM ledger WHERE seq IN ("
                "  SELECT MAX(seq) FROM ledger WHERE tenant_id=? AND document_id=? "
                "  GROUP BY target_field"
                ") ORDER BY target_field ASC",
                (tenant_id, document_id),
            ).fetchall()
        return [LedgerEntry.model_validate_json(r["payload"]) for r in rows]

    def verify_chain(self, tenant_id: str = "demo") -> tuple[bool, str | None]:
        """Recompute every hash in order. Returns (ok, first_broken_entry_hash)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload, prev_hash, entry_hash FROM ledger WHERE tenant_id=? "
                "ORDER BY seq ASC",
                (tenant_id,),
            ).fetchall()
        expected_prev = GENESIS_HASH
        for row in rows:
            entry = LedgerEntry.model_validate_json(row["payload"])
            if entry.prev_hash != expected_prev:
                return False, entry.entry_hash
            if compute_hash(entry) != row["entry_hash"]:
                return False, row["entry_hash"]
            expected_prev = row["entry_hash"]
        return True, None
