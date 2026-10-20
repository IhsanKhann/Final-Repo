"""Per-tenant precedents: what an analyst already decided, so we never ask a model twice.

Exists because this is the difference between learning and re-prompting. A precedent is a
stored fact -- (tenant, source_label) -> canonical field -- and a precedent hit resolves
with NO MODEL CALL AT ALL. That is what makes round 2 faster, cheaper, and provably
identical to what the analyst chose, rather than a second roll of the same dice.

The two counters this module exists to produce, precedents_applied and model_calls_skipped,
are the numbers that prove the loop is real. A system that re-prompted and happened to
agree would show zero skipped calls.

Round 3 promotion is deferred but its seam is here: corrections are counted per
(source_label, target_field), so promoting a thrice-corrected term into a PROPOSED pack
synonym is a query, not a redesign. The system proposes; the customer authors. That line
never moves, which is why promotion_candidates() returns candidates and nothing else.

What this module refuses to do:
  * It refuses to author a pack entry. It can only propose one.
  * It refuses to outrank the customer. A precedent sits below a QUOTED pack rule, and the
    authority order is enforced in engine/resolve.py, not negotiated here.
  * It refuses to forget. Feedback is append-only; the precedent table is a projection of
    it, so a precedent can always be rebuilt from the events that produced it.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from backend.engine.contracts import Authority, FeedbackEvent, Precedent

#: A term corrected this many times the same way becomes a promotion candidate for a
#: proposed pack synonym (README section 10, round 3).
PROMOTION_THRESHOLD = 3


class PromotionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    source_label: str
    target_field: str
    corrections: int
    #: PROPOSED, always. Nothing here is ever born accepted.
    status: str = "PROPOSED"


class PrecedentStore(ABC):
    """Interface written though there is one implementation; Firestore swaps in behind it."""

    @abstractmethod
    def record_feedback(self, event: FeedbackEvent) -> None: ...

    @abstractmethod
    def learn(self, event: FeedbackEvent) -> Precedent | None: ...

    @abstractmethod
    def lookup(self, source_label: str, tenant_id: str = "demo") -> Precedent | None: ...

    @abstractmethod
    def note_applied(self, source_label: str, tenant_id: str = "demo") -> None: ...

    @abstractmethod
    def all_precedents(self, tenant_id: str = "demo") -> list[Precedent]: ...

    @abstractmethod
    def feedback_events(self, tenant_id: str = "demo") -> list[FeedbackEvent]: ...

    @abstractmethod
    def promotion_candidates(
        self, tenant_id: str = "demo", threshold: int = PROMOTION_THRESHOLD
    ) -> list[PromotionCandidate]: ...


def _default_db_path() -> Path:
    import os

    # Overridable, like the ledger's. Without this every test and every run shared one
    # precedent store, so a "clean" run silently inherited corrections made hours earlier
    # and `precedents_applied` was not reproducible from a fresh checkout -- which is
    # exactly the number we use to prove the feedback loop is real.
    return Path(
        os.environ.get("MEMORY_DB_PATH")
        or Path(__file__).resolve().parent.parent / ".data" / "memory.db"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqlitePrecedentStore(PrecedentStore):
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
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload TEXT NOT NULL,
                    source_label TEXT NOT NULL, to_field TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS precedents (
                    tenant_id TEXT NOT NULL, source_label TEXT NOT NULL,
                    target_field TEXT NOT NULL, times_applied INTEGER NOT NULL DEFAULT 0,
                    learned_from_mapping_id TEXT, created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, source_label)
                );
                CREATE INDEX IF NOT EXISTS feedback_label
                    ON feedback (tenant_id, source_label, to_field);
                """
            )

    def record_feedback(self, event: FeedbackEvent) -> None:
        """Append-only. The precedent table is a projection of this."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feedback (id,tenant_id,payload,source_label,to_field,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    event.id,
                    event.tenant_id,
                    event.model_dump_json(),
                    event.source_label,
                    event.to_field,
                    event.created_at,
                ),
            )

    def learn(self, event: FeedbackEvent) -> Precedent | None:
        """Turn an analyst decision into a precedent, or return None if there is no lesson.

        An `accept` DOES teach, and this is the subtle part. The patch payload the frontend
        sends carries no target field, so an accept is the analyst saying "this source
        label does mean this field" -- which promotes a model-authority guess to an
        analyst-authority fact. Next round that label resolves with no model call. That is
        the whole mechanism, so refusing to learn from an accept would make the headline
        number unreachable.

        A `reject` teaches nothing, because the payload says the field was wrong without
        saying what is right. Inventing the correction would be us authoring the customer's
        meaning, which is the one thing this product exists to refuse.

        The caller decides whether a lesson is worth storing at all -- see
        feedback.apply_patch, which declines to write a precedent for a mapping the pack
        already resolved, so that precedents_applied counts only precedents that earned
        their keep.
        """
        if event.action == "reject":
            return None
        if not event.to_field:
            return None

        precedent = Precedent(
            tenant_id=event.tenant_id,
            source_label=event.source_label,
            target_field=event.to_field,
            authority=Authority.ANALYST,
            learned_from_mapping_id=event.mapping_id,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO precedents (tenant_id,source_label,target_field,times_applied,"
                "learned_from_mapping_id,created_at) VALUES (?,?,?,0,?,?) "
                "ON CONFLICT(tenant_id,source_label) DO UPDATE SET "
                "target_field=excluded.target_field, "
                "learned_from_mapping_id=excluded.learned_from_mapping_id",
                (
                    precedent.tenant_id,
                    precedent.source_label,
                    precedent.target_field,
                    precedent.learned_from_mapping_id,
                    precedent.created_at,
                ),
            )
        return precedent

    def lookup(self, source_label: str, tenant_id: str = "demo") -> Precedent | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM precedents WHERE tenant_id=? AND source_label=?",
                (tenant_id, source_label),
            ).fetchone()
        if row is None:
            return None
        return Precedent(
            tenant_id=row["tenant_id"],
            source_label=row["source_label"],
            target_field=row["target_field"],
            times_applied=row["times_applied"],
            learned_from_mapping_id=row["learned_from_mapping_id"],
            created_at=row["created_at"],
        )

    def note_applied(self, source_label: str, tenant_id: str = "demo") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE precedents SET times_applied = times_applied + 1 "
                "WHERE tenant_id=? AND source_label=?",
                (tenant_id, source_label),
            )

    def all_precedents(self, tenant_id: str = "demo") -> list[Precedent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM precedents WHERE tenant_id=? ORDER BY source_label", (tenant_id,)
            ).fetchall()
        return [
            Precedent(
                tenant_id=r["tenant_id"],
                source_label=r["source_label"],
                target_field=r["target_field"],
                times_applied=r["times_applied"],
                learned_from_mapping_id=r["learned_from_mapping_id"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def feedback_events(self, tenant_id: str = "demo") -> list[FeedbackEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM feedback WHERE tenant_id=? ORDER BY created_at", (tenant_id,)
            ).fetchall()
        return [FeedbackEvent.model_validate_json(r["payload"]) for r in rows]

    def promotion_candidates(
        self, tenant_id: str = "demo", threshold: int = PROMOTION_THRESHOLD
    ) -> list[PromotionCandidate]:
        """Terms corrected the same way `threshold` times. PROPOSED only, never applied."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source_label, to_field, COUNT(*) AS n FROM feedback "
                "WHERE tenant_id=? AND to_field IS NOT NULL "
                "GROUP BY source_label, to_field HAVING n >= ? ORDER BY n DESC",
                (tenant_id, threshold),
            ).fetchall()
        return [
            PromotionCandidate(
                tenant_id=tenant_id,
                source_label=r["source_label"],
                target_field=r["to_field"],
                corrections=int(r["n"]),
            )
            for r in rows
        ]
