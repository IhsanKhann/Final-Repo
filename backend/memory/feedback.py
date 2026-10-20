"""What happens when an analyst touches a mapping. The loop surfacing in the UI.

Exists because PATCH /api/mappings/{id} has to do two things at once: change this mapping
now, and change the next run. The second is the one the problem statement is actually
asking for, and `learned: true` with a `learned_message` is how the UI shows that it
happened -- the field already exists in the frontend's contract, so the loop is visible
rather than claimed.

What this module refuses to do:
  * It refuses to write a precedent for a mapping the pack already resolved. A pack rule
    outranks an analyst, so such a precedent would never be the thing that resolved the
    field, and counting it would inflate precedents_applied with entries that did no work.
  * It refuses to invent the correction behind a rejection. A reject says the field was
    wrong, not what is right.
  * It refuses to overwrite history. The FeedbackEvent is appended before anything else
    happens, so the precedent is always reconstructible from the events that caused it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from backend.engine.contracts import (
    Authority,
    FeedbackEvent,
    Mapping,
    MappingPatchPayload,
    MappingPatchResponse,
)
from backend.memory.precedents import PrecedentStore


@dataclass(frozen=True)
class PatchOutcome:
    """The response, plus the event, so a caller can ledger it without re-deriving."""

    response: MappingPatchResponse
    event: FeedbackEvent
    learned_precedent: bool


#: Statuses an analyst action produces. `accept` and `edit` both end approved, because in
#: both cases a human has signed off on the value that is now there.
_STATUS_FOR_ACTION = {"accept": "approved", "edit": "approved", "reject": "rejected"}


def apply_patch(
    mapping: Mapping,
    payload: MappingPatchPayload,
    store: PrecedentStore,
    *,
    actor: str = "analyst",
    prior_authority: Authority | None = None,
    event_id: str | None = None,
) -> PatchOutcome:
    """Apply one analyst decision to one mapping and learn from it where there is a lesson.

    `prior_authority` is how the caller tells us where this mapping's field came from. When
    it came from the pack, the accept is a confirmation of the customer's own rule and
    there is nothing to learn; when it came from a model, the accept is the lesson.
    """
    # An analyst may redirect the field, not just the value. When they do, the lesson is
    # the field they chose, which is why `to_field` below reads from the updated mapping
    # rather than echoing the one we proposed.
    chosen_field = (
        payload.target_field.strip()
        if payload.target_field and payload.target_field.strip()
        else mapping.target_field
    )

    updated = mapping.model_copy(
        update={
            "status": _STATUS_FOR_ACTION[payload.action],
            "target_field": chosen_field,
            "value": payload.value if payload.value is not None else mapping.value,
            "unit": payload.unit if payload.unit is not None else mapping.unit,
            "reason": payload.reason or mapping.reason,
            # A human signed this off, so it is certain regardless of what the model felt.
            "confidence": 1.0 if payload.action in ("accept", "edit") else mapping.confidence,
        }
    )

    teaches = payload.action in ("accept", "edit")
    pack_already_owns_this = prior_authority in (
        Authority.PACK_QUOTED,
        Authority.PACK_AUTHORED,
    )

    event = FeedbackEvent(
        id=event_id or f"fb-{uuid.uuid4().hex[:12]}",
        tenant_id="demo",
        mapping_id=mapping.id,
        document_id=mapping.document_id,
        source_label=mapping.source_label,
        action=payload.action,
        from_field=mapping.target_field,
        to_field=updated.target_field if teaches else None,
        from_value=mapping.value,
        to_value=updated.value,
        reason=payload.reason,
        actor=actor,
    )
    store.record_feedback(event)

    precedent = None
    if teaches and not pack_already_owns_this:
        precedent = store.learn(event)

    if precedent is not None:
        message = (
            f"Learned: {mapping.source_label!r} means {precedent.target_field}. "
            "The next run resolves it with no model call."
        )
    elif pack_already_owns_this:
        message = (
            "Recorded. No precedent was needed: the pack already declares this mapping, "
            "and a pack rule outranks a precedent."
        )
    else:
        message = (
            "Recorded. Nothing was learned from a rejection, because it says which field "
            "is wrong without saying which is right."
        )

    return PatchOutcome(
        response=MappingPatchResponse(
            mapping=updated,
            learned=precedent is not None,
            learned_message=message,
        ),
        event=event,
        learned_precedent=precedent is not None,
    )


@dataclass
class RoundCounters:
    """The two numbers that prove the loop is real rather than a re-prompt."""

    precedents_applied: int = 0
    model_calls_skipped: int = 0
    model_calls_made: int = 0

    def observe(self, *, used_model: bool, model_call_skipped: bool, by_precedent: bool) -> None:
        if used_model:
            self.model_calls_made += 1
        if model_call_skipped:
            self.model_calls_skipped += 1
        if by_precedent:
            self.precedents_applied += 1
