"""Prompt text and the enforced response schema, with an explicit version string.

Exists because `prompt_version` is one of the five controlled variables in the round
report (documents, pack version, model, temperature, prompt version). A prompt edited in
place without a version bump silently voids the comparison between two rounds, so the
string lives here beside the text it describes and `RoundReport.comparable` can be
computed from it.

What this module refuses to do:
  * It refuses to name a domain field. Every field name in a prompt arrives from the
    pack at call time (Law II). Nothing here knows what the customer measures.
  * It refuses to let the model invent a field. `mapping_choice_schema` closes the
    `target_field` property over the retrieved candidate list as an enum, so the enforced
    schema -- not a sentence in the prompt -- is what makes an out-of-list answer a
    protocol violation. mapper.py rejects it a second time anyway: a schema is a request,
    not a guarantee.
  * It refuses to do I/O. No file read, no template loader, no config lookup on import.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

#: Bump on every change to the text or the schema below. It reaches the UI through
#: Proposal.prompt_version and the round report, so an un-bumped edit is a lie about a
#: controlled variable.
PROMPT_VERSION = "map-v1"

#: Used as Proposal.prompt_version when a mapping resolved deterministically. Reads
#: honestly in the evidence drawer: there was no prompt, so there is no version.
NO_PROMPT = "none (no model call)"

MAPPER_SYSTEM = (
    "You arbitrate between candidate field names that a deterministic retriever has "
    "already found. You are not an extractor and not a validator.\n"
    "Rules you cannot break:\n"
    "1. target_field MUST be copied exactly from the numbered candidate list. Any other "
    "value, however reasonable, is rejected and the field is sent to a human.\n"
    "2. If no candidate is a genuine match, choose the closest one and give it a "
    "confidence at or below 0.4 so the gate sends it for review. Never invent a field "
    "name to express doubt.\n"
    "3. confidence is a number between 0 and 1 describing how certain the mapping is, "
    "not how common the field is.\n"
    "4. reason is one sentence a reviewer can argue with: say what in the source label "
    "or sample value decided it. Do not restate the question.\n"
    "Answer only through the provided schema."
)


def render_candidate_block(candidates: Sequence[Mapping[str, Any]]) -> str:
    """Numbered candidate list. Each item needs `target_field`; the rest is optional."""
    lines: list[str] = []
    for i, candidate in enumerate(candidates, start=1):
        field = candidate["target_field"]
        bits: list[str] = []
        unit = candidate.get("unit")
        if unit:
            bits.append(f"unit {unit}")
        matched_on = candidate.get("matched_on")
        if matched_on:
            bits.append(f"retrieved via {candidate.get('via', 'match')} on '{matched_on}'")
        synonyms = candidate.get("synonyms") or ()
        if synonyms:
            bits.append("declared synonyms: " + ", ".join(str(s) for s in synonyms))
        suffix = f" ({'; '.join(bits)})" if bits else ""
        lines.append(f"{i}. {field}{suffix}")
    return "\n".join(lines)


def render_mapping_user(
    *,
    source_label: str,
    candidates: Sequence[Mapping[str, Any]],
    sample_value: str | None = None,
    sample_unit: str | None = None,
    context: str | None = None,
    document_name: str | None = None,
) -> str:
    """The user turn. Deterministic for a given input, so two rounds are comparable."""
    parts = [f"Source label, verbatim from the document: {source_label!r}"]
    if sample_value is not None:
        shown = f"{sample_value!r}"
        if sample_unit:
            shown += f" (unit as written: {sample_unit!r})"
        parts.append(f"A value found under that label: {shown}")
    if document_name:
        parts.append(f"Document: {document_name}")
    if context:
        parts.append(f"Surrounding text: {context}")
    parts.append(
        "Candidate target fields declared by the customer's pack -- choose exactly one:\n"
        + render_candidate_block(candidates)
    )
    return "\n\n".join(parts)


def mapping_choice_schema(allowed_fields: Iterable[str]) -> dict[str, Any]:
    """The enforced response schema, closed over the retrieved candidates.

    `enum` is the mechanism: the choice is constrained to fields the pack declares, so an
    out-of-list answer is a schema violation rather than a plausible-looking guess.
    """
    allowed = list(dict.fromkeys(str(f) for f in allowed_fields))
    if not allowed:
        raise ValueError("an empty candidate list cannot be offered to the model")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["target_field", "confidence", "reason"],
        "properties": {
            "target_field": {
                "type": "string",
                "enum": allowed,
                "description": "Copied exactly from the candidate list.",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {
                "type": "string",
                "description": "One sentence a human reviewer can disagree with.",
            },
        },
    }


__all__ = [
    "MAPPER_SYSTEM",
    "NO_PROMPT",
    "PROMPT_VERSION",
    "mapping_choice_schema",
    "render_candidate_block",
    "render_mapping_user",
]
