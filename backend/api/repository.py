"""Storage behind an interface, so BigQuery/GCS cost one class and one env var.

Exists because CLAUDE.md 6b says a deferred capability must be addable by swapping one
implementation behind an interface that exists today. There is exactly one implementation
now (SQLite); `REPOSITORY=bigquery` selects another later without touching a route, a
service or a test.

What this module refuses to do:
  * It refuses to raise across its seam. A missing row is `None`, never an exception, so
    the caller decides whether absence is a 404 or an empty list (CLAUDE.md 6).
  * It refuses to accept a call without a tenant. `tenant_id` is a parameter AND a column
    on every table NOW, defaulted to "demo", because adding auth later must cost one
    middleware and not a signature change in every file.
  * It refuses to interpret. It stores and returns contract models verbatim; deciding what
    a row means belongs to the engine.
  * It refuses to hold a connection open. One connection per call, like config.py, so
    nothing goes stale and nothing is shared across threads.

Rows are stored as the contract model's own JSON plus the few columns worth querying on.
That is deliberate: the shape of truth is `engine/contracts.py`, not a schema migration,
and a column-per-field table would have to change every time types.ts grows a field.
"""

from __future__ import annotations

import os
import sqlite3
from abc import ABC, abstractmethod
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.engine.config import DEFAULT_TENANT
from backend.engine.contracts import (
    AgentEvent,
    Batch,
    Document,
    FeedbackEvent,
    Mapping,
    RoundReport,
)

__all__ = ["Repository", "SqliteRepository", "make_repository", "DEFAULT_TENANT"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- The interface ------------------------------------------------------------


class Repository(ABC):
    """Everything the API persists. Written as an interface with one implementation.

    Every method takes `tenant_id` as a keyword with a default, and every row carries it.
    Reads never raise: a single-row getter returns `None` when the row is absent and a
    list getter returns `[]`.
    """

    # -- batches ---------------------------------------------------------------

    @abstractmethod
    def upsert_batch(self, batch: Batch, *, tenant_id: str = DEFAULT_TENANT) -> None: ...

    @abstractmethod
    def get_batch(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Batch | None: ...

    @abstractmethod
    def list_batches(
        self, *, tenant_id: str = DEFAULT_TENANT, limit: int = 100
    ) -> list[Batch]: ...

    # -- documents -------------------------------------------------------------

    @abstractmethod
    def upsert_document(self, document: Document, *, tenant_id: str = DEFAULT_TENANT) -> None: ...

    @abstractmethod
    def get_document(
        self, document_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> Document | None: ...

    @abstractmethod
    def list_documents(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> list[Document]: ...

    # -- mappings --------------------------------------------------------------

    @abstractmethod
    def upsert_mapping(self, mapping: Mapping, *, tenant_id: str = DEFAULT_TENANT) -> None: ...

    @abstractmethod
    def get_mapping(
        self, mapping_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> Mapping | None: ...

    @abstractmethod
    def list_mappings(
        self,
        *,
        tenant_id: str = DEFAULT_TENANT,
        document_id: str | None = None,
        batch_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> list[Mapping]:
        """Mappings, narrowed. `batch_id` resolves through the documents table.

        `statuses` is how the review queue is read without the caller knowing SQL: pass
        ("review", "missing") and you have the tray.
        """

    @abstractmethod
    def record_keys(
        self,
        *,
        tenant_id: str = DEFAULT_TENANT,
        document_id: str | None = None,
        batch_id: str | None = None,
    ) -> dict[str, str]:
        """mapping id -> which record inside its document it belongs to.

        A lookup rather than a second list_mappings variant that returns pairs: one source
        of mappings cannot drift from another, and a caller that forgets the keys gets a
        document-level grouping rather than a silently different set of rows.
        """

    # -- events ----------------------------------------------------------------

    @abstractmethod
    def append_event(
        self, batch_id: str, event: AgentEvent, *, tenant_id: str = DEFAULT_TENANT
    ) -> None: ...

    @abstractmethod
    def list_events(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> list[AgentEvent]:
        """Events for a batch in emission order.

        `after_seq` exists for the SSE swap: a stream resumes from the last sequence it
        delivered instead of replaying the batch. The MVP poller passes 0.
        """

    @abstractmethod
    def event_seq(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> int:
        """Highest sequence number recorded for a batch; 0 when there are none."""

    # -- feedback --------------------------------------------------------------

    @abstractmethod
    def append_feedback(
        self, feedback: FeedbackEvent, *, tenant_id: str = DEFAULT_TENANT
    ) -> None:
        """Append-only. This is the learning signal; nothing may overwrite it."""

    @abstractmethod
    def list_feedback(
        self, *, tenant_id: str = DEFAULT_TENANT, limit: int = 200
    ) -> list[FeedbackEvent]: ...

    # -- round reports ---------------------------------------------------------

    @abstractmethod
    def save_round_report(self, report: RoundReport, *, tenant_id: str = DEFAULT_TENANT) -> None: ...

    @abstractmethod
    def list_round_reports(self, *, tenant_id: str = DEFAULT_TENANT) -> list[RoundReport]: ...

    # -- liveness --------------------------------------------------------------

    @abstractmethod
    def ping(self) -> tuple[bool, str]:
        """(reachable, human message). Never raises; /api/health calls this."""


# --- The one implementation ---------------------------------------------------


def _default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".data" / "api.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, created_at TEXT, updated_at TEXT,
    stage TEXT, status TEXT, pack_id TEXT, body TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS documents (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, batch_id TEXT, status TEXT,
    created_at TEXT, body TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS ix_documents_batch ON documents (tenant_id, batch_id);
CREATE TABLE IF NOT EXISTS mappings (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, document_id TEXT, target_field TEXT,
    source_label TEXT, status TEXT, confidence REAL, updated_at TEXT, body TEXT NOT NULL,
    -- Which record inside the document. One source document can hold many records, so
    -- grouping the gold table by document alone showed 1 row where there were 30.
    -- It is a column rather than a field on Mapping because types.ts does not declare
    -- one; if it gains `record_key?`, this column and list_mapping_records go away.
    record_key TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS ix_mappings_record
    ON mappings (tenant_id, document_id, record_key);
CREATE INDEX IF NOT EXISTS ix_mappings_document ON mappings (tenant_id, document_id);
CREATE INDEX IF NOT EXISTS ix_mappings_status ON mappings (tenant_id, status);
CREATE TABLE IF NOT EXISTS events (
    tenant_id TEXT NOT NULL, seq INTEGER NOT NULL, batch_id TEXT NOT NULL, id TEXT NOT NULL,
    timestamp TEXT, body TEXT NOT NULL,
    PRIMARY KEY (tenant_id, batch_id, seq)
);
CREATE TABLE IF NOT EXISTS feedback (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, mapping_id TEXT, document_id TEXT,
    created_at TEXT, body TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS round_reports (
    tenant_id TEXT NOT NULL, round INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (tenant_id, round)
);
"""


class SqliteRepository(Repository):
    """Local storage. One connection per call; no singleton to go stale.

    The JSON body is the record; the columns beside it exist only so a query does not have
    to parse every row. When a body fails to validate against the current contract the row
    is skipped rather than crashing a page: a schema that moved under us degrades the list,
    it does not 500 the app.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("API_DB_PATH") or _default_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    # -- plumbing --------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)
            # CREATE TABLE IF NOT EXISTS does nothing to a table that already exists, so a
            # database created before record_key needs the column added explicitly. Guarded
            # by a read of the existing columns rather than by catching the error, so a
            # genuine failure here is still loud.
            existing = {row[1] for row in conn.execute("PRAGMA table_info(mappings)")}
            if "record_key" not in existing:
                conn.execute(
                    "ALTER TABLE mappings ADD COLUMN record_key TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _decode(model, raw: str):
        """Validate a stored body, or return None. Never raises: see class docstring."""
        try:
            return model.model_validate_json(raw)
        except Exception:
            return None

    def _decode_all(self, model, rows) -> list:
        out = [self._decode(model, r["body"]) for r in rows]
        return [x for x in out if x is not None]

    # -- batches ---------------------------------------------------------------

    def upsert_batch(self, batch: Batch, *, tenant_id: str = DEFAULT_TENANT) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO batches (tenant_id,id,created_at,updated_at,stage,status,pack_id,body)"
                " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,id) DO UPDATE SET"
                " updated_at=excluded.updated_at, stage=excluded.stage,"
                " status=excluded.status, pack_id=excluded.pack_id, body=excluded.body",
                (
                    tenant_id,
                    batch.id,
                    batch.created_at,
                    batch.updated_at,
                    batch.stage,
                    batch.status,
                    batch.pack_id,
                    batch.model_dump_json(),
                ),
            )

    def get_batch(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Batch | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT body FROM batches WHERE tenant_id=? AND id=?", (tenant_id, batch_id)
            ).fetchone()
        return None if row is None else self._decode(Batch, row["body"])

    def list_batches(self, *, tenant_id: str = DEFAULT_TENANT, limit: int = 100) -> list[Batch]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT body FROM batches WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, int(limit)),
            ).fetchall()
        return self._decode_all(Batch, rows)

    # -- documents -------------------------------------------------------------

    def upsert_document(self, document: Document, *, tenant_id: str = DEFAULT_TENANT) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO documents (tenant_id,id,batch_id,status,created_at,body)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(tenant_id,id) DO UPDATE SET"
                " batch_id=excluded.batch_id, status=excluded.status, body=excluded.body",
                (
                    tenant_id,
                    document.id,
                    document.batch_id,
                    document.status,
                    document.created_at,
                    document.model_dump_json(),
                ),
            )

    def get_document(
        self, document_id: str, *, tenant_id: str = DEFAULT_TENANT
    ) -> Document | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT body FROM documents WHERE tenant_id=? AND id=?", (tenant_id, document_id)
            ).fetchone()
        return None if row is None else self._decode(Document, row["body"])

    def list_documents(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> list[Document]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT body FROM documents WHERE tenant_id=? AND batch_id=? ORDER BY created_at",
                (tenant_id, batch_id),
            ).fetchall()
        return self._decode_all(Document, rows)

    # -- mappings --------------------------------------------------------------

    def upsert_mapping(
        self,
        mapping: Mapping,
        *,
        tenant_id: str = DEFAULT_TENANT,
        record_key: str | None = None,
    ) -> None:
        """Store a mapping. `record_key=None` leaves an existing key untouched.

        That matters for corrections: PATCH re-stores a mapping without knowing which
        record it belongs to, and overwriting the key with "" would drop the row it came
        from out of the gold table.
        """
        with closing(self._connect()) as conn, conn:
            if record_key is None:
                row = conn.execute(
                    "SELECT record_key FROM mappings WHERE tenant_id=? AND id=?",
                    (tenant_id, mapping.id),
                ).fetchone()
                record_key = (row["record_key"] if row else "") or ""
            conn.execute(
                "INSERT INTO mappings (tenant_id,id,document_id,target_field,source_label,"
                "status,confidence,updated_at,body,record_key) VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(tenant_id,id) DO UPDATE SET document_id=excluded.document_id,"
                " target_field=excluded.target_field, source_label=excluded.source_label,"
                " status=excluded.status, confidence=excluded.confidence,"
                " updated_at=excluded.updated_at, body=excluded.body,"
                " record_key=excluded.record_key",
                (
                    tenant_id,
                    mapping.id,
                    mapping.document_id,
                    mapping.target_field,
                    mapping.source_label,
                    mapping.status,
                    mapping.confidence,
                    _now(),
                    mapping.model_dump_json(),
                    record_key,
                ),
            )

    def get_mapping(self, mapping_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Mapping | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT body FROM mappings WHERE tenant_id=? AND id=?", (tenant_id, mapping_id)
            ).fetchone()
        return None if row is None else self._decode(Mapping, row["body"])

    def record_keys(
        self,
        *,
        tenant_id: str = DEFAULT_TENANT,
        document_id: str | None = None,
        batch_id: str | None = None,
    ) -> dict[str, str]:
        sql = ["SELECT m.id AS id, m.record_key AS record_key FROM mappings m"]
        params: list[object] = []
        if batch_id is not None:
            sql.append(
                " JOIN documents d ON d.tenant_id = m.tenant_id AND d.id = m.document_id"
            )
        sql.append(" WHERE m.tenant_id=?")
        params.append(tenant_id)
        if document_id is not None:
            sql.append(" AND m.document_id=?")
            params.append(document_id)
        if batch_id is not None:
            sql.append(" AND d.batch_id=?")
            params.append(batch_id)
        with closing(self._connect()) as conn:
            rows = conn.execute("".join(sql), tuple(params)).fetchall()
        return {r["id"]: (r["record_key"] or "") for r in rows}

    def list_mappings(
        self,
        *,
        tenant_id: str = DEFAULT_TENANT,
        document_id: str | None = None,
        batch_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> list[Mapping]:
        sql = ["SELECT m.body AS body FROM mappings m"]
        params: list[object] = []
        if batch_id is not None:
            sql.append(
                " JOIN documents d ON d.tenant_id = m.tenant_id AND d.id = m.document_id"
            )
        sql.append(" WHERE m.tenant_id=?")
        params.append(tenant_id)
        if document_id is not None:
            sql.append(" AND m.document_id=?")
            params.append(document_id)
        if batch_id is not None:
            sql.append(" AND d.batch_id=?")
            params.append(batch_id)
        if statuses:
            sql.append(f" AND m.status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        sql.append(" ORDER BY m.id")
        with closing(self._connect()) as conn:
            rows = conn.execute("".join(sql), tuple(params)).fetchall()
        return self._decode_all(Mapping, rows)

    # -- events ----------------------------------------------------------------

    def append_event(
        self, batch_id: str, event: AgentEvent, *, tenant_id: str = DEFAULT_TENANT
    ) -> None:
        with closing(self._connect()) as conn, conn:
            nxt = conn.execute(
                "SELECT COALESCE(MAX(seq),0)+1 AS n FROM events WHERE tenant_id=? AND batch_id=?",
                (tenant_id, batch_id),
            ).fetchone()["n"]
            conn.execute(
                "INSERT INTO events (tenant_id,seq,batch_id,id,timestamp,body)"
                " VALUES (?,?,?,?,?,?)",
                (tenant_id, nxt, batch_id, event.id, event.timestamp, event.model_dump_json()),
            )

    def list_events(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> list[AgentEvent]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT body FROM events WHERE tenant_id=? AND batch_id=? AND seq>? ORDER BY seq",
                (tenant_id, batch_id, int(after_seq)),
            ).fetchall()
        return self._decode_all(AgentEvent, rows)

    def event_seq(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq),0) AS n FROM events WHERE tenant_id=? AND batch_id=?",
                (tenant_id, batch_id),
            ).fetchone()
        return int(row["n"])

    # -- feedback --------------------------------------------------------------

    def append_feedback(
        self, feedback: FeedbackEvent, *, tenant_id: str = DEFAULT_TENANT
    ) -> None:
        with closing(self._connect()) as conn, conn:
            # No ON CONFLICT clause on purpose: feedback is append-only and a duplicate id
            # is a bug worth seeing, not a silent overwrite of the learning signal.
            conn.execute(
                "INSERT OR IGNORE INTO feedback (tenant_id,id,mapping_id,document_id,"
                "created_at,body) VALUES (?,?,?,?,?,?)",
                (
                    tenant_id,
                    feedback.id,
                    feedback.mapping_id,
                    feedback.document_id,
                    feedback.created_at,
                    feedback.model_dump_json(),
                ),
            )

    def list_feedback(
        self, *, tenant_id: str = DEFAULT_TENANT, limit: int = 200
    ) -> list[FeedbackEvent]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT body FROM feedback WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, int(limit)),
            ).fetchall()
        return self._decode_all(FeedbackEvent, rows)

    # -- round reports ---------------------------------------------------------

    def save_round_report(self, report: RoundReport, *, tenant_id: str = DEFAULT_TENANT) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO round_reports (tenant_id,round,body) VALUES (?,?,?)"
                " ON CONFLICT(tenant_id,round) DO UPDATE SET body=excluded.body",
                (tenant_id, int(report.round), report.model_dump_json()),
            )

    def list_round_reports(self, *, tenant_id: str = DEFAULT_TENANT) -> list[RoundReport]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT body FROM round_reports WHERE tenant_id=? ORDER BY round", (tenant_id,)
            ).fetchall()
        return self._decode_all(RoundReport, rows)

    # -- liveness --------------------------------------------------------------

    def ping(self) -> tuple[bool, str]:
        try:
            with closing(self._connect()) as conn:
                conn.execute("SELECT 1").fetchone()
            return True, f"sqlite at {self.db_path.name}"
        except Exception as exc:  # containment: health reports, it does not crash
            return False, f"sqlite unreachable: {type(exc).__name__}"


def make_repository() -> Repository:
    """Pick the implementation by one env var. That is the whole BigQuery migration."""
    kind = (os.environ.get("REPOSITORY") or "sqlite").strip().lower()
    if kind == "sqlite":
        return SqliteRepository()
    if kind in {"bigquery", "firestore"}:
        raise NotImplementedError(
            f"{kind} Repository belongs to the infra lane. Set REPOSITORY=sqlite to run locally."
        )
    raise ValueError(f"unknown REPOSITORY {kind!r}; expected 'sqlite'")
