"""The agent activity log, written from day one so SSE is one function, not a rewrite.

The contract says `GET /api/batches/{id}/events` is an SSE stream; the MVP serves a JSON
array and the UI polls. That difference must live in exactly one place, so the event SHAPE
is `contracts.AgentEvent` on both sides of the swap and the ordering/resume mechanics
(`after_seq`) already exist. Turning the poller into a stream is then: iterate `stream()`
and yield `f"data: {event.model_dump_json()}\\n\\n"`.

What this module refuses to do:
  * It refuses to raise. A log that can break the run it is describing is worse than no
    log, so `emit` swallows storage failures and `read` returns [] on a bad read.
  * It refuses to invent a timestamp order. Sequence comes from the store, not from the
    clock, because two events inside one millisecond must still be orderable.
  * It refuses to be the place a pipeline reports progress *to the engine*. It is an
    outbound record for humans; nothing may read it back to make a decision.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Iterator, Literal

from backend.api.repository import Repository
from backend.engine.config import DEFAULT_TENANT
from backend.engine.contracts import AgentEvent

__all__ = ["EventLog", "RepositoryEventLog", "NullEventLog", "new_event"]


def new_event(
    agent: str,
    step: str,
    status: Literal["running", "done", "error"],
    message: str,
    *,
    file_id: str | None = None,
) -> AgentEvent:
    """Build an AgentEvent with an id and a UTC timestamp. The only constructor."""
    return AgentEvent(
        id=f"evt-{uuid.uuid4().hex[:12]}",
        agent=agent,
        step=step,
        status=status,
        message=message,
        timestamp=datetime.now(timezone.utc).isoformat(),
        file_id=file_id,
    )


class EventLog(ABC):
    """Append-and-read for agent activity. One implementation today, by design."""

    @abstractmethod
    def emit(
        self, batch_id: str, event: AgentEvent, *, tenant_id: str = DEFAULT_TENANT
    ) -> None: ...

    @abstractmethod
    def read(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> list[AgentEvent]: ...

    @abstractmethod
    def seq(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> int: ...

    def stream(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> Iterator[AgentEvent]:
        """The SSE seam. Today it drains what exists; tomorrow it tails.

        The route that becomes an SSE endpoint consumes exactly this iterator, so the
        swap touches this method and nothing else.
        """
        yield from self.read(batch_id, tenant_id=tenant_id, after_seq=after_seq)


class RepositoryEventLog(EventLog):
    """Events in the Repository, so they move to BigQuery with everything else."""

    def __init__(self, repository: Repository) -> None:
        self._repo = repository

    def emit(self, batch_id: str, event: AgentEvent, *, tenant_id: str = DEFAULT_TENANT) -> None:
        try:
            self._repo.append_event(batch_id, event, tenant_id=tenant_id)
        except Exception:
            # Containment: a log write must never take down the run it describes.
            pass

    def read(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> list[AgentEvent]:
        try:
            return self._repo.list_events(batch_id, tenant_id=tenant_id, after_seq=after_seq)
        except Exception:
            return []

    def seq(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> int:
        try:
            return self._repo.event_seq(batch_id, tenant_id=tenant_id)
        except Exception:
            return 0


class NullEventLog(EventLog):
    """For tests and for a service that has no interest in being observed."""

    def emit(self, batch_id: str, event: AgentEvent, *, tenant_id: str = DEFAULT_TENANT) -> None:
        return None

    def read(
        self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT, after_seq: int = 0
    ) -> list[AgentEvent]:
        return []

    def seq(self, batch_id: str, *, tenant_id: str = DEFAULT_TENANT) -> int:
        return 0
