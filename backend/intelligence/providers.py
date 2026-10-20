"""Four provider rows, two wire dialects, and not one byte of network code.

Exists so that "which provider" is a row of data and "which wire format" is the only
polymorphic thing in the system. There is no router class per provider and no second
SDK wrapper: a provider is `Provider(base_url, dialect, models_need_key, ...)`, and the
dialect selects two pure functions -- `shape_request` and `parse_response`.

What this module refuses to do:
  * It refuses to open a socket, import an HTTP client, or import a vendor SDK. Request
    shaping and response parsing are pure, so both dialects are tested with no key and
    no wifi by feeding a recorded response dict in and asserting the parse. Transport is
    injected from `base.py`; see `Transport` there.
  * It refuses to read a key. Keys come from `engine.config.secret_for`, resolved by the
    caller and passed in. Nothing here touches the process environment or a .env file.
  * It refuses to collapse failures into a boolean. Every failure is one of the named
    states in `FailureState`, which mirrors the `Unavailable.reason` literals exactly --
    a test asserts the two lists are the same, because a drifted name would reach the
    Health banner as a blank reason.
  * It refuses to treat a listed model as a callable one. `/models` returns models that
    404 for keys issued after a provider's cutoff, so `model-unavailable` is its own
    state rather than a flavour of `bad-key` or `provider-down`.
"""

from __future__ import annotations

import json
from enum import Enum
from string import Formatter
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

# --- The two dialects ---------------------------------------------------------


class Dialect(str, Enum):
    """The only polymorphic thing. Two wire formats, four providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


#: Spelled out so the PROVIDERS table below reads like the table in README section 6.
OPENAI = Dialect.OPENAI
ANTHROPIC = Dialect.ANTHROPIC


class AuthStyle(str, Enum):
    BEARER = "bearer"  # Authorization: Bearer <key>
    X_API_KEY = "x-api-key"  # x-api-key: <key>


#: Pinned by the Anthropic Messages API; it is a required header, not a nicety.
ANTHROPIC_API_VERSION = "2023-06-01"


# --- A provider is a row ------------------------------------------------------


class Provider(BaseModel):
    """One row of the providers table. Data, not behaviour."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    base_url: str
    dialect: Dialect
    #: False only for OpenRouter, whose catalogue answers unauthenticated, so the model
    #: picker populates before anyone has pasted a key.
    models_need_key: bool
    #: The id in engine.config.SECRETS that holds this provider's key. This module never
    #: resolves it; the caller passes the resolved value in.
    secret_id: str
    auth_style: AuthStyle
    #: A model we have actually called, not one scraped from /models. See the module
    #: docstring on model-unavailable.
    default_model: str
    chat_path: str
    models_path: str


PROVIDERS: dict[str, Provider] = {
    "openai": Provider(
        id="openai",
        base_url="https://api.openai.com/v1",
        dialect=OPENAI,
        models_need_key=True,
        secret_id="openai_api_key",
        auth_style=AuthStyle.BEARER,
        default_model="gpt-4o-2024-11-20",
        chat_path="/chat/completions",
        models_path="/models",
    ),
    "openrouter": Provider(
        id="openrouter",
        base_url="https://openrouter.ai/api/v1",
        dialect=OPENAI,
        models_need_key=False,
        secret_id="openrouter_api_key",
        auth_style=AuthStyle.BEARER,
        default_model="openai/gpt-4o-2024-11-20",
        chat_path="/chat/completions",
        models_path="/models",
    ),
    "google": Provider(
        id="google",
        # The Vertex OpenAI-compatibility endpoint. It is project- and location-scoped,
        # so the row carries a template and `base_url_for` fills it from config -- a bare
        # hostname here would be a URL that cannot be called.
        base_url=(
            "https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
            "/locations/{location}/endpoints/openapi"
        ),
        dialect=OPENAI,
        models_need_key=True,
        secret_id="google_api_key",
        auth_style=AuthStyle.BEARER,
        default_model="google/gemini-2.0-flash-001",
        chat_path="/chat/completions",
        models_path="/models",
    ),
    "anthropic": Provider(
        id="anthropic",
        base_url="https://api.anthropic.com/v1",
        dialect=ANTHROPIC,
        models_need_key=True,
        secret_id="anthropic_api_key",
        auth_style=AuthStyle.X_API_KEY,
        default_model="claude-sonnet-4-5-20250929",
        chat_path="/messages",
        models_path="/models",
    ),
}


def provider_for(provider_id: str) -> Provider | None:
    """None rather than KeyError: an unknown provider id is a config value, not a bug."""
    return PROVIDERS.get((provider_id or "").strip().lower())


def base_url_for(
    provider_id: str, *, project: str | None = None, location: str = "us-central1"
) -> str:
    """Fill any placeholders in a row's base_url. Pure; raises only on a missing value."""
    provider = provider_for(provider_id)
    if provider is None:
        raise KeyError(f"unknown provider {provider_id!r}; known: {sorted(PROVIDERS)}")
    placeholders = {name for _, name, _, _ in Formatter().parse(provider.base_url) if name}
    if not placeholders:
        return provider.base_url
    values = {"project": project, "location": location}
    missing = sorted(p for p in placeholders if not values.get(p))
    if missing:
        raise ValueError(
            f"provider {provider_id!r} base_url needs {missing}; pass them from config"
        )
    return provider.base_url.format(**values)


def auth_headers(provider: Provider, api_key: str | None) -> dict[str, str]:
    """Headers for a row. Separate from shape_request so the body stays key-free."""
    headers = {"content-type": "application/json"}
    if provider.auth_style is AuthStyle.BEARER:
        headers["authorization"] = f"Bearer {api_key or ''}"
    else:
        headers["x-api-key"] = api_key or ""
        headers["anthropic-version"] = ANTHROPIC_API_VERSION
    return headers


# --- Named failure states -----------------------------------------------------


class FailureState(str, Enum):
    """Mirrors contracts.Unavailable.reason exactly. A test asserts that, by value."""

    NO_KEY = "no-key"
    BAD_KEY = "bad-key"
    MODEL_UNAVAILABLE = "model-unavailable"
    RATE_LIMITED = "rate-limited"
    TIMEOUT = "timeout"
    PROVIDER_DOWN = "provider-down"


#: Substrings a provider uses when the model name itself is the problem. A 400 or 404
#: carrying one of these is `model-unavailable`, not `bad-key` and not `provider-down`:
#: the key works, the account simply cannot call that model.
_MODEL_PROBLEM_MARKERS = (
    "model_not_found",
    "does not exist",
    "no such model",
    "unknown model",
    "not_found_error",
    "model not supported",
    "unsupported model",
)


def _body_text(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, str):
        return body.lower()
    try:
        return json.dumps(body).lower()
    except (TypeError, ValueError):
        return str(body).lower()


def preflight(provider: Provider, api_key: str | None) -> FailureState | None:
    """The one failure knowable before a request exists. None means 'go ahead'."""
    if provider.models_need_key and not api_key:
        return FailureState.NO_KEY
    return None


def classify_http_status(status: int, body: Any = None) -> FailureState | None:
    """Map a response status onto a named state. None means the response is usable."""
    if 200 <= status < 300:
        return None
    text = _body_text(body)
    if status in (401, 403):
        return FailureState.BAD_KEY
    if status == 404:
        return FailureState.MODEL_UNAVAILABLE
    if status == 429:
        return FailureState.RATE_LIMITED
    if status in (408, 504, 524):
        return FailureState.TIMEOUT
    if status == 400 and any(m in text for m in _MODEL_PROBLEM_MARKERS):
        return FailureState.MODEL_UNAVAILABLE
    if status >= 500:
        return FailureState.PROVIDER_DOWN
    # Any other 4xx is a request we built wrong. It is reported as provider-down with the
    # body kept in `detail`, because the honest alternative -- inventing a seventh state
    # the frontend cannot render -- is worse than a named state plus the real message.
    return FailureState.PROVIDER_DOWN


# --- Request shaping (pure) ---------------------------------------------------


class ShapedRequest(BaseModel):
    """A request as data: path, body, and what we deliberately did not send.

    `temperature_sent` and `omission_reason` exist so the round report can state the real
    setting per provider. A dict alone has nowhere to record that the standard's
    temperature 0 never went on the wire, and a report claiming a temperature that was
    never sent is the kind of quiet lie this project is built to refuse.
    """

    model_config = ConfigDict(extra="forbid")

    dialect: Dialect
    path: str
    body: dict[str, Any]
    #: The temperature actually in `body`. None means it was omitted on purpose.
    temperature_sent: float | None = None
    omitted_params: tuple[str, ...] = ()
    omission_reason: str | None = None


#: Current Anthropic models removed `temperature`, `top_p` and `seed` from the Messages
#: API; sending any of them returns HTTP 400. The standard's temperature 0 is still the
#: intent, and these models are deterministic-by-default for our purposes, but the value
#: cannot be transmitted -- so the ANTHROPIC branch omits it and records why here.
ANTHROPIC_SAMPLING_OMITTED = (
    "anthropic-messages-rejects-sampling-params: current Anthropic models removed "
    "temperature/top_p/seed from the API and return HTTP 400 if one is sent, so "
    "temperature 0 is the intent but is not transmitted"
)
ANTHROPIC_OMITTED_PARAMS = ("temperature", "top_p", "seed")

#: The name the enforced schema is bound to on both dialects: `json_schema.name` for
#: OpenAI, the forced tool name for Anthropic.
SCHEMA_NAME = "field_mapping_choice"


def shape_request(
    dialect: Dialect | str,
    *,
    model: str,
    system: str,
    user: str,
    schema: Mapping[str, Any],
    max_tokens: int,
    temperature: float = 0.0,
    schema_name: str = SCHEMA_NAME,
    schema_description: str = "Return the chosen mapping exactly once.",
) -> ShapedRequest:
    """Build the wire body for one dialect. Pure: no key, no clock, no socket.

    Returns the shaped request rather than a bare dict because the ANTHROPIC branch has
    to report a parameter it did not send; `shape_request_body` gives the dict alone for
    callers that only want to hand it to a transport.
    """
    dialect = Dialect(dialect)
    if dialect is Dialect.OPENAI:
        body: dict[str, Any] = {
            "model": model,
            # Supported and mandated on this dialect. Pinned model + temperature 0 is
            # what makes a round report comparable.
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": dict(schema),
                },
            },
        }
        return ShapedRequest(
            dialect=dialect,
            path="/chat/completions",
            body=body,
            temperature_sent=temperature,
        )

    # --- ANTHROPIC -----------------------------------------------------------
    # No "temperature" key, by necessity rather than preference: see
    # ANTHROPIC_SAMPLING_OMITTED above. Structured output on this dialect is a forced
    # tool call, which is the enforced-schema equivalent of response_format.
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": [{"type": "text", "text": user}]}],
        "tools": [
            {
                "name": schema_name,
                "description": schema_description,
                "input_schema": dict(schema),
            }
        ],
        "tool_choice": {"type": "tool", "name": schema_name},
    }
    return ShapedRequest(
        dialect=dialect,
        path="/messages",
        body=body,
        temperature_sent=None,
        omitted_params=ANTHROPIC_OMITTED_PARAMS,
        omission_reason=ANTHROPIC_SAMPLING_OMITTED,
    )


def shape_request_body(dialect: Dialect | str, **kwargs: Any) -> dict[str, Any]:
    """The wire dict alone, for a caller that does not need the omission record."""
    return shape_request(dialect, **kwargs).body


# --- Response parsing (pure) --------------------------------------------------


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ParsedReply(BaseModel):
    """What a recorded response dict parses into. `data is None` means non-conforming."""

    model_config = ConfigDict(extra="forbid")

    #: The structured payload, already validated as a JSON object. None if the reply did
    #: not conform to the enforced schema shape.
    data: dict[str, Any] | None = None
    #: The raw text the provider returned, kept for the review tray and for `detail`.
    text: str = ""
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    #: Why the reply is non-conforming. None when data is present.
    problem: str | None = None

    @property
    def conforming(self) -> bool:
        return self.data is not None


def _as_object(raw_text: str) -> tuple[dict[str, Any] | None, str | None]:
    if not raw_text.strip():
        return None, "empty reply"
    try:
        loaded = json.loads(raw_text)
    except (TypeError, ValueError) as exc:
        return None, f"reply is not JSON: {exc}"
    if not isinstance(loaded, dict):
        return None, f"reply is JSON {type(loaded).__name__}, not an object"
    return loaded, None


def parse_response(dialect: Dialect | str, raw: Mapping[str, Any]) -> ParsedReply:
    """Turn one recorded response dict into a ParsedReply. Pure; never raises.

    A malformed reply is a ParsedReply with `problem` set, not an exception: the retry
    policy in base.py is the only thing allowed to decide what a bad reply costs.
    """
    dialect = Dialect(dialect)
    if not isinstance(raw, Mapping):
        return ParsedReply(problem=f"response is {type(raw).__name__}, not an object")

    if dialect is Dialect.OPENAI:
        usage_raw = raw.get("usage") or {}
        usage = Usage(
            input_tokens=int(usage_raw.get("prompt_tokens") or 0),
            output_tokens=int(usage_raw.get("completion_tokens") or 0),
        )
        choices = raw.get("choices") or []
        if not choices:
            return ParsedReply(usage=usage, problem="no choices in reply")
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        finish = choice.get("finish_reason")
        if content is None:
            # A refusal field is the structured-output refusal path; it is a real reply
            # and still non-conforming for our purposes.
            refusal = message.get("refusal")
            return ParsedReply(
                usage=usage,
                finish_reason=finish,
                text=str(refusal or ""),
                problem="reply carried no content" + (" (refusal)" if refusal else ""),
            )
        text = content if isinstance(content, str) else json.dumps(content)
        data, problem = _as_object(text)
        return ParsedReply(
            data=data, text=text, finish_reason=finish, usage=usage, problem=problem
        )

    # --- ANTHROPIC: structured output arrives as a forced tool_use block -------
    usage_raw = raw.get("usage") or {}
    usage = Usage(
        input_tokens=int(usage_raw.get("input_tokens") or 0),
        output_tokens=int(usage_raw.get("output_tokens") or 0),
    )
    finish = raw.get("stop_reason")
    blocks = raw.get("content") or []
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "tool_use":
            payload = block.get("input")
            if isinstance(payload, Mapping):
                return ParsedReply(
                    data=dict(payload),
                    text=json.dumps(dict(payload)),
                    finish_reason=finish,
                    usage=usage,
                )
            return ParsedReply(
                usage=usage,
                finish_reason=finish,
                text=str(payload),
                problem="tool_use input was not an object",
            )
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
    if not texts:
        return ParsedReply(usage=usage, finish_reason=finish, problem="no content blocks")
    text = "\n".join(texts)
    # The tool was forced, so plain text is already off-contract. Parse it anyway: if it
    # happens to be the right object we accept it, otherwise it is non-conforming.
    data, problem = _as_object(text)
    if data is None and problem is None:  # defensive: _as_object always pairs them
        problem = "model answered with text instead of the forced tool call"
    return ParsedReply(
        data=data, text=text, finish_reason=finish, usage=usage, problem=problem
    )


__all__ = [
    "ANTHROPIC",
    "ANTHROPIC_API_VERSION",
    "ANTHROPIC_OMITTED_PARAMS",
    "ANTHROPIC_SAMPLING_OMITTED",
    "OPENAI",
    "PROVIDERS",
    "SCHEMA_NAME",
    "AuthStyle",
    "Dialect",
    "FailureState",
    "ParsedReply",
    "Provider",
    "ShapedRequest",
    "Usage",
    "auth_headers",
    "base_url_for",
    "classify_http_status",
    "parse_response",
    "preflight",
    "provider_for",
    "shape_request",
    "shape_request_body",
]
