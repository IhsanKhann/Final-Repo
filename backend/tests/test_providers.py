"""Both dialects, every named failure state, no key and no wifi.

These tests are the reason providers.py contains no network code. A recorded response
dict goes in, an assertion comes out, and the suite is green on a laptop in a tunnel with
`OPENAI_API_KEY` unset -- which is also exactly the condition the demo has to survive.

Nothing here imports `openai` or `anthropic`. The SDKs are listed in requirements.txt but
the block does not depend on them: at the time of writing `anthropic` is not installed in
this environment and the ANTHROPIC dialect is still fully tested, because a dialect is two
pure functions and a transport is an injected Protocol.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, get_args

import pytest

from backend.engine.config import SECRETS, ConfigStore, Source
from backend.engine.contracts import Unavailable
from backend.intelligence import providers as prov
from backend.intelligence.base import (
    RetryPolicy,
    Seam,
    TokenBudget,
    TransportReply,
    TransportTimeout,
    TransportUnreachable,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
INTELLIGENCE = REPO_ROOT / "backend" / "intelligence"

# A deliberately tiny schema, so the expected request bodies below can be literals.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["target_field"],
    "properties": {"target_field": {"type": "string", "enum": ["field_one", "field_two"]}},
}


@pytest.fixture(autouse=True)
def no_key_anywhere(monkeypatch):
    """Run every test as if no key had ever been configured, on any machine.

    `secret_for` treats env as a one-time seed, so a key exported in the developer's
    shell would otherwise be promoted into the store mid-test and the `no-key` assertions
    below would pass or fail depending on whose laptop ran them.
    """
    for env_var in SECRETS.values():
        monkeypatch.delenv(env_var, raising=False)


# --- fakes --------------------------------------------------------------------


class FakeTransport:
    """Records every call and replays queued replies. The last reply repeats."""

    def __init__(self, *replies: TransportReply | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        timeout_s: float,
    ) -> TransportReply:
        self.calls.append(
            {"url": url, "headers": dict(headers), "body": dict(body), "timeout_s": timeout_s}
        )
        item = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class EmptyStore(ConfigStore):
    """A config store with nothing in it: no controls, no secrets, no file on disk."""

    def get_control(self, tenant_id: str, key: str) -> str | None:
        return None

    def set_control(self, tenant_id, key, value, source, updated_by) -> None:
        raise AssertionError("a read-only test wrote a control")

    def get_secret(self, tenant_id: str, secret_id: str) -> str | None:
        return None

    def set_secret(self, tenant_id, secret_id, value, source, updated_by) -> None:
        raise AssertionError("a read-only test wrote a secret")

    def list_controls(self, tenant_id: str) -> dict[str, str]:
        return {}

    def list_secret_ids(self, tenant_id: str) -> list[str]:
        return []

    def get_last_known_good(self, tenant_id: str, key: str) -> str | None:
        return None

    def record_last_known_good(self, tenant_id: str, key: str, value: Any) -> None:
        return None


def openai_seam(*replies: TransportReply | Exception, **kwargs: Any) -> tuple[Seam, FakeTransport]:
    transport = FakeTransport(*replies)
    slept: list[float] = []
    seam = Seam(
        provider=prov.PROVIDERS["openai"],
        model="test-model-1",
        api_key="sk-test",
        max_tokens=256,
        transport=transport,
        sleep=slept.append,
        **kwargs,
    )
    seam.slept = slept  # type: ignore[attr-defined]
    return seam, transport


def ok_openai_reply(content: str = '{"target_field": "field_one"}') -> TransportReply:
    return TransportReply(
        status=200,
        payload={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        },
    )


def call(seam: Seam) -> Any:
    return seam.structured(system="SYS", user="USR", schema=SCHEMA)


# --- the four rows ------------------------------------------------------------


def test_the_providers_table_is_four_rows_of_data():
    assert sorted(prov.PROVIDERS) == ["anthropic", "google", "openai", "openrouter"]
    assert prov.PROVIDERS["openai"].base_url == "https://api.openai.com/v1"
    assert prov.PROVIDERS["openrouter"].base_url == "https://openrouter.ai/api/v1"
    assert prov.PROVIDERS["anthropic"].base_url == "https://api.anthropic.com/v1"
    # Google is the Vertex OpenAI-compatibility endpoint, which is project-scoped.
    assert prov.PROVIDERS["google"].base_url.endswith("/endpoints/openapi")
    assert "aiplatform.googleapis.com" in prov.PROVIDERS["google"].base_url


def test_three_of_the_four_rows_share_one_dialect():
    dialects = {pid: p.dialect for pid, p in prov.PROVIDERS.items()}
    assert dialects == {
        "openai": prov.OPENAI,
        "openrouter": prov.OPENAI,
        "google": prov.OPENAI,
        "anthropic": prov.ANTHROPIC,
    }
    assert len({p.dialect for p in prov.PROVIDERS.values()}) == 2


def test_only_openrouters_catalogue_answers_without_a_key():
    needs = {pid: p.models_need_key for pid, p in prov.PROVIDERS.items()}
    assert needs == {
        "openai": True,
        "openrouter": False,
        "google": True,
        "anthropic": True,
    }


def test_the_vertex_base_url_is_filled_from_config_not_guessed():
    url = prov.base_url_for("google", project="proj-1", location="europe-west4")
    assert url == (
        "https://europe-west4-aiplatform.googleapis.com/v1/projects/proj-1"
        "/locations/europe-west4/endpoints/openapi"
    )
    # Unfilled placeholders are an error, not a URL that 404s at 3am.
    with pytest.raises(ValueError):
        prov.base_url_for("google", project=None)
    assert prov.base_url_for("openai") == "https://api.openai.com/v1"


def test_each_dialect_authenticates_the_way_its_provider_demands():
    openai_headers = prov.auth_headers(prov.PROVIDERS["openai"], "sk-1")
    assert openai_headers["authorization"] == "Bearer sk-1"
    anthropic_headers = prov.auth_headers(prov.PROVIDERS["anthropic"], "sk-2")
    assert anthropic_headers["x-api-key"] == "sk-2"
    assert anthropic_headers["anthropic-version"] == prov.ANTHROPIC_API_VERSION
    assert "authorization" not in anthropic_headers


# --- request shaping, asserted against literals -------------------------------


def test_the_openai_dialect_body_is_exactly_this_and_carries_temperature_zero():
    shaped = prov.shape_request(
        prov.OPENAI,
        model="test-model-1",
        system="SYS",
        user="USR",
        schema=SCHEMA,
        max_tokens=256,
        temperature=0.0,
    )
    assert shaped.path == "/chat/completions"
    assert shaped.body == {
        "model": "test-model-1",
        "temperature": 0.0,
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USR"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "field_mapping_choice",
                "strict": True,
                "schema": SCHEMA,
            },
        },
    }
    assert shaped.body["temperature"] == 0
    assert shaped.temperature_sent == 0.0
    assert shaped.omitted_params == ()


def test_the_anthropic_dialect_body_is_exactly_this_and_has_no_temperature_key():
    shaped = prov.shape_request(
        prov.ANTHROPIC,
        model="test-model-1",
        system="SYS",
        user="USR",
        schema=SCHEMA,
        max_tokens=256,
        temperature=0.0,
    )
    assert shaped.path == "/messages"
    assert shaped.body == {
        "model": "test-model-1",
        "max_tokens": 256,
        "system": "SYS",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "USR"}]}],
        "tools": [
            {
                "name": "field_mapping_choice",
                "description": "Return the chosen mapping exactly once.",
                "input_schema": SCHEMA,
            }
        ],
        "tool_choice": {"type": "tool", "name": "field_mapping_choice"},
    }
    # The whole point: not temperature 0, no temperature at all.
    assert "temperature" not in shaped.body
    assert "top_p" not in shaped.body
    assert "seed" not in shaped.body


def test_the_omitted_temperature_is_recorded_rather_than_silently_dropped():
    """A round report must be able to state the real setting per provider.

    Current Anthropic models removed temperature/top_p/seed from the Messages API and
    return HTTP 400 if one is sent, so the value cannot go on the wire. Dropping it
    quietly would leave the report claiming a temperature that was never sent.
    """
    shaped = prov.shape_request(
        prov.ANTHROPIC,
        model="m",
        system="s",
        user="u",
        schema=SCHEMA,
        max_tokens=16,
        temperature=0.0,
    )
    assert shaped.temperature_sent is None
    assert shaped.omitted_params == ("temperature", "top_p", "seed")
    assert shaped.omission_reason == prov.ANTHROPIC_SAMPLING_OMITTED
    assert "400" in shaped.omission_reason


def test_the_dict_only_helper_returns_the_same_body():
    kwargs = dict(
        model="m", system="s", user="u", schema=SCHEMA, max_tokens=16, temperature=0.0
    )
    for dialect in (prov.OPENAI, prov.ANTHROPIC):
        assert prov.shape_request_body(dialect, **kwargs) == prov.shape_request(
            dialect, **kwargs
        ).body


def test_both_dialects_enforce_a_response_schema_rather_than_asking_nicely():
    openai_body = prov.shape_request_body(
        prov.OPENAI, model="m", system="s", user="u", schema=SCHEMA, max_tokens=16
    )
    assert openai_body["response_format"]["json_schema"]["strict"] is True
    anthropic_body = prov.shape_request_body(
        prov.ANTHROPIC, model="m", system="s", user="u", schema=SCHEMA, max_tokens=16
    )
    # The Anthropic equivalent of a response schema is a forced tool call.
    assert anthropic_body["tool_choice"] == {"type": "tool", "name": "field_mapping_choice"}
    assert anthropic_body["tools"][0]["input_schema"] == SCHEMA


# --- response parsing, from recorded dicts ------------------------------------


def test_a_recorded_openai_response_parses_without_a_socket():
    parsed = prov.parse_response(
        prov.OPENAI,
        {
            "choices": [
                {
                    "message": {"content": '{"target_field": "field_one", "confidence": 0.8}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        },
    )
    assert parsed.conforming
    assert parsed.data == {"target_field": "field_one", "confidence": 0.8}
    assert parsed.finish_reason == "stop"
    assert parsed.usage.total_tokens == 150


def test_a_recorded_anthropic_tool_use_response_parses_without_a_socket():
    parsed = prov.parse_response(
        prov.ANTHROPIC,
        {
            "content": [
                {
                    "type": "tool_use",
                    "name": "field_mapping_choice",
                    "input": {"target_field": "field_two", "confidence": 0.7},
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 200, "output_tokens": 40},
        },
    )
    assert parsed.conforming
    assert parsed.data == {"target_field": "field_two", "confidence": 0.7}
    assert parsed.usage.total_tokens == 240


@pytest.mark.parametrize(
    "dialect,raw",
    [
        (prov.OPENAI, {"choices": [{"message": {"content": "I think it is field_one."}}]}),
        (prov.OPENAI, {"choices": []}),
        (prov.OPENAI, {"choices": [{"message": {"refusal": "no"}}]}),
        (prov.ANTHROPIC, {"content": [{"type": "text", "text": "field_two, probably"}]}),
        (prov.ANTHROPIC, {"content": []}),
    ],
)
def test_a_non_conforming_reply_parses_to_a_problem_not_an_exception(dialect, raw):
    parsed = prov.parse_response(dialect, raw)
    assert parsed.data is None
    assert parsed.conforming is False
    assert parsed.problem


# --- the named failure states -------------------------------------------------


def test_every_failure_state_is_a_reason_the_contract_declares():
    allowed = set(get_args(Unavailable.model_fields["reason"].annotation))
    assert {s.value for s in prov.FailureState} <= allowed
    # And the six the standard names are all present, spelled the contract's way.
    assert {s.value for s in prov.FailureState} == {
        "no-key",
        "bad-key",
        "model-unavailable",
        "rate-limited",
        "timeout",
        "provider-down",
    }


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, {}, None),
        (401, {}, prov.FailureState.BAD_KEY),
        (403, {}, prov.FailureState.BAD_KEY),
        (404, {}, prov.FailureState.MODEL_UNAVAILABLE),
        (429, {}, prov.FailureState.RATE_LIMITED),
        (408, {}, prov.FailureState.TIMEOUT),
        (504, {}, prov.FailureState.TIMEOUT),
        (500, {}, prov.FailureState.PROVIDER_DOWN),
        (503, {}, prov.FailureState.PROVIDER_DOWN),
        (
            400,
            {"error": {"code": "model_not_found", "message": "the model does not exist"}},
            prov.FailureState.MODEL_UNAVAILABLE,
        ),
    ],
)
def test_each_status_maps_to_its_named_state(status, body, expected):
    assert prov.classify_http_status(status, body) is expected


def test_a_listed_model_that_404s_is_model_unavailable_not_a_dead_provider():
    """`/models` offers models that 404 for keys issued after a provider's cutoff.

    Folding that into provider-down would send an operator to the status page when the
    fix is to change one control value.
    """
    seam, transport = openai_seam(TransportReply(status=404, text="model_not_found"))
    outcome = call(seam)
    assert isinstance(outcome, Unavailable)
    assert outcome.reason == "model-unavailable"
    assert len(transport.calls) == 1


def test_no_key_is_decided_before_a_request_exists():
    transport = FakeTransport(ok_openai_reply())
    seam = Seam(
        provider=prov.PROVIDERS["openai"], model="m", api_key=None, transport=transport
    )
    outcome = call(seam)
    assert isinstance(outcome, Unavailable) and outcome.reason == "no-key"
    assert transport.calls == [], "no-key must cost nothing; nothing was sent"


def test_openrouter_needs_no_key_to_be_tried_because_its_row_says_so():
    transport = FakeTransport(ok_openai_reply())
    seam = Seam(
        provider=prov.PROVIDERS["openrouter"], model="m", api_key=None, transport=transport
    )
    assert call(seam) == {"target_field": "field_one"}
    assert len(transport.calls) == 1


def test_a_rejected_key_is_bad_key():
    seam, _ = openai_seam(TransportReply(status=401, text="invalid_api_key"))
    outcome = call(seam)
    assert isinstance(outcome, Unavailable) and outcome.reason == "bad-key"
    assert "401" in (outcome.detail or "")


def test_a_429_backs_off_exponentially_and_then_names_itself_rate_limited():
    seam, transport = openai_seam(
        TransportReply(status=429, text="slow down"),
        retry=RetryPolicy(rate_limit_attempts=3, backoff_base_s=0.5),
    )
    outcome = call(seam)
    assert isinstance(outcome, Unavailable) and outcome.reason == "rate-limited"
    assert len(transport.calls) == 3
    assert seam.slept == [0.5, 1.0]  # type: ignore[attr-defined]


def test_a_429_that_clears_on_retry_returns_the_answer():
    seam, transport = openai_seam(
        TransportReply(status=429, text="slow down"), ok_openai_reply()
    )
    assert call(seam) == {"target_field": "field_one"}
    assert len(transport.calls) == 2


def test_the_hard_timeout_is_named_timeout_and_is_not_retried():
    seam, transport = openai_seam(TransportTimeout("30s elapsed"))
    outcome = call(seam)
    assert isinstance(outcome, Unavailable) and outcome.reason == "timeout"
    assert len(transport.calls) == 1


def test_an_unreachable_or_exploding_provider_is_provider_down():
    seam, _ = openai_seam(TransportUnreachable("dns failure"))
    first = call(seam)
    assert isinstance(first, Unavailable) and first.reason == "provider-down"

    seam2, _ = openai_seam(TransportReply(status=503, text="upstream unavailable"))
    second = call(seam2)
    assert isinstance(second, Unavailable) and second.reason == "provider-down"

    # Even a transport that raises something nobody anticipated. The seam never raises.
    seam3, _ = openai_seam(RuntimeError("a bug in someone else's library"))
    third = call(seam3)
    assert isinstance(third, Unavailable) and third.reason == "provider-down"
    assert "RuntimeError" in (third.detail or "")


def test_a_missing_transport_degrades_instead_of_raising():
    seam = Seam(provider=prov.PROVIDERS["openai"], model="m", api_key="sk-test")
    outcome = call(seam)
    assert isinstance(outcome, Unavailable) and outcome.reason == "provider-down"


def test_an_unknown_provider_id_degrades_the_run_instead_of_aborting_it():
    seam = Seam.from_config(store=EmptyStore(), session={"provider": "not-a-provider"})
    outcome = call(seam)
    assert isinstance(outcome, Unavailable) and outcome.reason == "provider-down"
    assert "not-a-provider" in (outcome.detail or "")


def test_an_exhausted_document_budget_is_its_own_state():
    seam, transport = openai_seam(ok_openai_reply(), budget=TokenBudget(0))
    outcome = call(seam)
    assert isinstance(outcome, Unavailable) and outcome.reason == "budget-exhausted"
    assert transport.calls == []


def test_the_budget_is_charged_from_the_replys_own_usage():
    budget = TokenBudget(1000)
    seam, _ = openai_seam(ok_openai_reply(), budget=budget)
    assert call(seam) == {"target_field": "field_one"}
    assert budget.spent == 18  # 11 prompt + 7 completion, as recorded
    assert budget.remaining == 982


# --- the retry rule -----------------------------------------------------------


def test_a_non_conforming_reply_is_retried_exactly_once_then_unavailable():
    seam, transport = openai_seam(ok_openai_reply(content="field_one, I reckon"))
    outcome = call(seam)
    assert isinstance(outcome, Unavailable)
    assert outcome.reason == "non-conforming-reply"
    assert len(transport.calls) == 2, "one retry, not none and not a loop"


def test_a_non_conforming_reply_followed_by_a_good_one_is_accepted():
    seam, transport = openai_seam(
        ok_openai_reply(content="not json at all"), ok_openai_reply()
    )
    assert call(seam) == {"target_field": "field_one"}
    assert len(transport.calls) == 2


# --- config wiring ------------------------------------------------------------


def test_the_seam_reads_the_five_controlled_variables_from_config_not_the_environment():
    seam = Seam.from_config(
        store=EmptyStore(),
        session={
            "provider": "anthropic",
            "model": "pinned-model-9",
            "temperature": 0.0,
            "max_tokens": 321,
            "timeout_s": 7,
            "prompt_version": "map-v1",
            "anthropic_api_key": "sk-session",
        },
        transport=FakeTransport(),
    )
    assert seam.provider.id == "anthropic"
    assert (seam.model, seam.temperature, seam.max_tokens) == ("pinned-model-9", 0.0, 321)
    assert (seam.timeout_s, seam.prompt_version) == (7.0, "map-v1")
    assert seam.api_key == "sk-session"
    assert seam.fatal is None


def test_with_no_key_anywhere_the_seam_says_no_key_rather_than_failing_the_run():
    """The documented no-key state, produced by the real resolver over an empty store."""
    seam = Seam.from_config(
        store=EmptyStore(), session={"provider": "openai"}, transport=FakeTransport()
    )
    assert seam.api_key is None
    outcome = call(seam)
    assert isinstance(outcome, Unavailable) and outcome.reason == "no-key"


def test_the_seam_records_what_it_actually_sent_per_dialect():
    transport = FakeTransport(
        TransportReply(
            status=200,
            payload={
                "content": [{"type": "tool_use", "input": {"target_field": "field_one"}}],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 5, "output_tokens": 5},
            },
        )
    )
    seam = Seam(
        provider=prov.PROVIDERS["anthropic"],
        model="m",
        api_key="sk-test",
        temperature=0.0,
        transport=transport,
    )
    assert call(seam) == {"target_field": "field_one"}
    assert "temperature" not in transport.calls[0]["body"]
    assert seam.last_request is not None
    assert seam.last_request.temperature_sent is None
    assert seam.last_request.omission_reason == prov.ANTHROPIC_SAMPLING_OMITTED


def test_the_source_enum_is_the_one_the_settings_page_shows():
    """Sanity check on the config contract this block depends on."""
    assert Source.ENV_SEED.value == "env-seed"


# --- import-time purity -------------------------------------------------------

_IMPORT_PROBE = """
import socket, sqlite3, sys


def boom(*args, **kwargs):
    raise AssertionError("I/O at import time")


socket.socket = boom
socket.create_connection = boom
socket.getaddrinfo = boom
sqlite3.connect = boom

import backend.intelligence.providers
import backend.intelligence.prompts
import backend.intelligence.base
import backend.intelligence.mapper

print("clean")
"""


def test_no_module_under_intelligence_performs_io_at_import_time():
    """Importing this block must not open a socket or the config database.

    Run in a subprocess with socket and sqlite3 sabotaged, because a module that connects
    on import makes the whole suite depend on the network it is supposed to prove we do
    not need.
    """
    result = subprocess.run(
        # No -I: isolated mode ignores PYTHONPATH, and PYTHONPATH is how the child finds
        # the repo. The probe sabotages socket and sqlite3 itself, which is the isolation
        # this test actually needs.
        [sys.executable, "-c", _IMPORT_PROBE],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        # ⚠ stdin=DEVNULL is required, not tidiness. Under pytest's capture on Windows the
        # inherited stdin handle is already closed, and Popen's _make_inheritable raises
        # OSError [WinError 6] "The handle is invalid" before the child ever starts -- so
        # the test fails for a reason that has nothing to do with what it asserts.
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


def test_no_module_under_intelligence_reads_a_key_from_the_environment():
    """Keys come from secret_for, and .env is loaded by entry points only.

    A library that reads os.environ directly bypasses the store that owns the value, so
    the key an operator just replaced in Settings loses to the stale one in a file.
    """
    offences: list[str] = []
    for path in sorted(INTELLIGENCE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(source.splitlines(), start=1):
            code = line.split("#", 1)[0]
            if "os.environ" in code or "getenv" in code or "load_env" in code:
                offences.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offences, "intelligence read config out of band:\n" + "\n".join(offences)


def test_the_provider_module_contains_no_transport_at_all():
    """providers.py is data plus two pure functions. HTTP lives in base.py's Transport."""
    source = (INTELLIGENCE / "providers.py").read_text(encoding="utf-8")
    for forbidden in ("import httpx", "import requests", "urlopen", "import openai", "import anthropic"):
        assert forbidden not in source, f"providers.py reached for {forbidden}"


def test_neither_sdk_is_imported_anywhere_in_the_block():
    """`anthropic` is not installed here and the ANTHROPIC dialect is still fully tested."""
    for path in sorted(INTELLIGENCE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "import openai" not in source, path.name
        assert "import anthropic" not in source, path.name
