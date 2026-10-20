"""The seam. Everything model-shaped crosses here, and nothing raises on the way out.

Exists for one decision: `Proposal | Unavailable`, never an exception. That is what turns
a provider outage into a degraded banner instead of a failed run -- precedent matches
still resolve, the rest queue for review, and the Health page says why.

It owns the four non-negotiable model settings (CLAUDE.md section 4): structured output
with an enforced response schema, a per-document token budget, a hard timeout, and
exponential backoff on 429. A non-conforming reply is exactly one retry, then
`Unavailable("non-conforming-reply")` -- which means the review tray, never a guess.

What this module refuses to do:
  * It refuses to raise across the seam. Every exit is a value. `except Exception` with
    no re-raise is deliberate here and nowhere else in the codebase.
  * It refuses to own transport. `Transport` is a Protocol the caller injects, so every
    failure state is reproducible with no key and no wifi. The one real implementation,
    `httpx_transport()`, imports its client inside the function body: this module must
    stay importable on a machine with no HTTP library and no vendor SDK installed.
  * It refuses to import a vendor SDK at all. The dialects are two pure functions in
    providers.py, so `openai` or `anthropic` being absent cannot break an import or a
    test.
  * It refuses to retry its way past a bad answer. Backoff is for 429 only; a
    non-conforming reply gets one retry because the second one is a guess with extra
    steps.
  * It refuses to read a key from the environment. Keys arrive from
    `engine.config.secret_for`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from backend.engine import config as cfg
from backend.engine.contracts import Proposal, ProposalOutcome, Unavailable
from backend.intelligence import providers as prov

# --- Transport seam -----------------------------------------------------------


class TransportReply(BaseModel):
    """One HTTP response as plain data, so a test can record and replay it."""

    model_config = ConfigDict(extra="forbid")

    status: int
    #: The decoded JSON body, or None when the body was not a JSON object. Named
    #: `payload` rather than `json` because a pydantic field called `json` shadows
    #: BaseModel.json and warns.
    payload: dict[str, Any] | None = None
    text: str = ""


class TransportTimeout(Exception):
    """The hard timeout elapsed. A transport raises this; the seam names it `timeout`."""


class TransportUnreachable(Exception):
    """DNS, TLS or connection failure. The seam names it `provider-down`."""


@runtime_checkable
class Transport(Protocol):
    """Anything that can post JSON and come back with a status. Injected, never built."""

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        timeout_s: float,
    ) -> TransportReply: ...


def httpx_transport() -> Transport:
    """The one real transport. Imports httpx inside the body, on purpose.

    If httpx is not installed this raises here, at wiring time, instead of making this
    module -- and every test in this block -- unimportable.
    """
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "httpx is not installed; inject a Transport or pip install httpx"
        ) from exc

    class _HttpxTransport:
        def post(
            self,
            url: str,
            *,
            headers: Mapping[str, str],
            body: Mapping[str, Any],
            timeout_s: float,
        ) -> TransportReply:
            try:
                response = httpx.post(
                    url, headers=dict(headers), json=dict(body), timeout=timeout_s
                )
            except httpx.TimeoutException as exc:
                raise TransportTimeout(str(exc)) from exc
            except httpx.TransportError as exc:
                raise TransportUnreachable(str(exc)) from exc
            try:
                payload = response.json()
            except ValueError:
                payload = None
            return TransportReply(
                status=response.status_code,
                payload=payload if isinstance(payload, dict) else None,
                text=response.text,
            )

    return _HttpxTransport()


# --- Per-document token budget ------------------------------------------------


class TokenBudget:
    """Tokens one document may spend. Shared across every call for that document.

    Not a pydantic model because it is a counter, not a boundary type. Exhaustion is a
    named outcome (`budget-exhausted`), not an exception: a document that runs out of
    budget still produces rows, in the review tray.
    """

    def __init__(self, limit: int) -> None:
        self.limit = int(limit)
        self.spent = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def exhausted(self) -> bool:
        return self.remaining <= 0

    def charge(self, tokens: int) -> None:
        self.spent += max(0, int(tokens))


@dataclass(frozen=True)
class RetryPolicy:
    """Backoff is for 429 only. One retry for a non-conforming reply. Nothing else."""

    rate_limit_attempts: int = 3
    backoff_base_s: float = 0.5
    backoff_cap_s: float = 8.0
    non_conforming_retries: int = 1

    def delay_for(self, attempt: int) -> float:
        """Exponential: base, 2x base, 4x base ... capped."""
        return min(self.backoff_cap_s, self.backoff_base_s * (2**attempt))


# --- The seam -----------------------------------------------------------------


@dataclass
class Seam:
    """One configured way to call a model. Returns values; never raises.

    `fatal` carries a failure known before any request exists (an unknown provider id, a
    base_url that cannot be built). It is returned from every call rather than raised at
    construction, because a misconfigured provider must degrade the run, not abort it.
    """

    provider: prov.Provider
    model: str
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout_s: float = 30.0
    prompt_version: str = "v1"
    transport: Transport | None = None
    budget: TokenBudget | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Callable[[float], None] = time.sleep
    project: str | None = None
    location: str = "us-central1"
    fatal: Unavailable | None = None
    #: Incremented on every exchange actually attempted. The round report's
    #: model_calls_skipped is the complement of this.
    calls_made: int = 0
    #: The last request we shaped, kept so the round report can read
    #: `temperature_sent` instead of assuming the configured temperature went on the wire.
    last_request: prov.ShapedRequest | None = None

    # --- construction ---------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        *,
        transport: Transport | None = None,
        store: cfg.ConfigStore | None = None,
        session: dict[str, Any] | None = None,
        tenant_id: str = cfg.DEFAULT_TENANT,
        budget: TokenBudget | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> "Seam":
        """Resolve the five controlled variables and the key. Lazy: never at import."""

        def resolved(key: str) -> Any:
            return cfg.control(key, store=store, session=session, tenant_id=tenant_id).value

        provider_id = str(resolved("provider") or "")
        provider = prov.provider_for(provider_id)
        if provider is None:
            return cls(
                provider=prov.PROVIDERS["openai"],
                model=str(resolved("model") or ""),
                transport=transport,
                sleep=sleep,
                fatal=Unavailable(
                    reason="provider-down",
                    detail=(
                        f"unknown provider {provider_id!r}; "
                        f"known: {sorted(prov.PROVIDERS)}"
                    ),
                ),
            )
        key = cfg.secret_for(
            provider.secret_id, store=store, session=session, tenant_id=tenant_id
        ).value
        limit = resolved("token_budget_per_doc")
        return cls(
            provider=provider,
            model=str(resolved("model") or provider.default_model),
            api_key=key or None,
            temperature=float(resolved("temperature") or 0.0),
            max_tokens=int(resolved("max_tokens") or 1024),
            timeout_s=float(resolved("timeout_s") or 30),
            prompt_version=str(resolved("prompt_version") or "v1"),
            transport=transport,
            budget=budget or TokenBudget(int(limit or 40000)),
            sleep=sleep,
        )

    # --- one exchange ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return (
            prov.base_url_for(self.provider.id, project=self.project, location=self.location)
            + path
        )

    def _exchange(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> prov.ParsedReply | Unavailable:
        """One request, with 429 backoff. Returns a parsed reply or a named failure."""
        if self.fatal is not None:
            return self.fatal
        state = prov.preflight(self.provider, self.api_key)
        if state is not None:
            return Unavailable(
                reason=state.value,
                detail=f"{self.provider.id} needs a key; none resolved from the config store",
            )
        if self.transport is None:
            return Unavailable(
                reason="provider-down",
                detail="no transport injected; intelligence cannot reach a provider",
            )
        if self.budget is not None and self.budget.exhausted():
            return Unavailable(
                reason="budget-exhausted",
                detail=f"document token budget of {self.budget.limit} is spent",
            )

        cap = self.max_tokens
        if self.budget is not None:
            cap = max(1, min(cap, self.budget.remaining))

        try:
            shaped = prov.shape_request(
                self.provider.dialect,
                model=self.model,
                system=system,
                user=user,
                schema=schema,
                max_tokens=cap,
                temperature=self.temperature,
            )
            url = self._url(shaped.path)
            headers = prov.auth_headers(self.provider, self.api_key)
        except Exception as exc:  # the seam never raises
            return Unavailable(
                reason="provider-down", detail=f"{type(exc).__name__}: {exc}"
            )

        self.last_request = shaped

        for attempt in range(max(1, self.retry.rate_limit_attempts)):
            self.calls_made += 1
            try:
                reply = self.transport.post(
                    url, headers=headers, body=shaped.body, timeout_s=self.timeout_s
                )
            except TransportTimeout as exc:
                # No retry: the timeout is the budget. Retrying doubles the wall clock a
                # reviewer is waiting on and the field is going to the tray either way.
                return Unavailable(reason="timeout", detail=str(exc) or f"{self.timeout_s}s")
            except TransportUnreachable as exc:
                return Unavailable(reason="provider-down", detail=str(exc))
            except Exception as exc:
                return Unavailable(
                    reason="provider-down", detail=f"{type(exc).__name__}: {exc}"
                )

            failure = prov.classify_http_status(reply.status, reply.payload or reply.text)
            if failure is None:
                parsed = prov.parse_response(self.provider.dialect, reply.payload or {})
                if self.budget is not None:
                    self.budget.charge(parsed.usage.total_tokens)
                return parsed

            if (
                failure is prov.FailureState.RATE_LIMITED
                and attempt + 1 < self.retry.rate_limit_attempts
            ):
                self.sleep(self.retry.delay_for(attempt))
                continue

            return Unavailable(
                reason=failure.value,
                detail=f"HTTP {reply.status} from {self.provider.id}: "
                f"{(reply.text or str(reply.payload or ''))[:400]}",
            )

        return Unavailable(
            reason="rate-limited",
            detail=f"{self.provider.id} returned 429 on "
            f"{self.retry.rate_limit_attempts} attempts",
        )

    # --- structured output ----------------------------------------------------

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        validate: Callable[[Mapping[str, Any]], str | None] | None = None,
    ) -> dict[str, Any] | Unavailable:
        """The enforced-schema call. Returns the payload or a named failure.

        `validate` returns None to accept or a sentence explaining the rejection. It gets
        the same single retry a malformed reply gets, which is how an out-of-list field
        name is retried once and then sent to the tray instead of being accepted.
        """
        problem: str | None = None
        attempts = 1 + max(0, self.retry.non_conforming_retries)
        for _ in range(attempts):
            outcome = self._exchange(system=system, user=user, schema=schema)
            if isinstance(outcome, Unavailable):
                return outcome
            if not outcome.conforming:
                problem = outcome.problem or "reply did not conform to the schema"
                continue
            payload = outcome.data or {}
            if validate is not None:
                rejection = validate(payload)
                if rejection:
                    problem = rejection
                    continue
            return dict(payload)
        return Unavailable(reason="non-conforming-reply", detail=problem)

    def propose(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        build: Callable[[Mapping[str, Any]], Proposal],
        validate: Callable[[Mapping[str, Any]], str | None] | None = None,
    ) -> ProposalOutcome:
        """`Proposal | Unavailable`. The only thing the pipeline is allowed to see."""
        payload = self.structured(system=system, user=user, schema=schema, validate=validate)
        if isinstance(payload, Unavailable):
            return payload
        try:
            return build(payload)
        except Exception as exc:
            # The payload passed the schema and `validate` and still would not become a
            # Proposal (a confidence out of range, say). That is non-conforming, not a
            # crash, and the field goes to the tray.
            return Unavailable(
                reason="non-conforming-reply",
                detail=f"{type(exc).__name__}: {exc}",
            )


__all__ = [
    "RetryPolicy",
    "Seam",
    "TokenBudget",
    "Transport",
    "TransportReply",
    "TransportTimeout",
    "TransportUnreachable",
    "httpx_transport",
]
