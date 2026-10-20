"""Bring-your-own-model, asserted: a catalogue with no key, and six named failures.

README section 6 makes a product claim -- a customer pastes their own key, picks any model
it reaches, and two models are A/B'd on the same documents without a code change -- and
adds that one catalogue "needs no key, so the picker populates before anyone signs in".
These tests are what make that claim checkable rather than aspirational.

Every catalogue fetch here goes through an injected transport, so the suite is green with
no key and no wifi -- the same condition the demo has to survive, and the reason
`intelligence/providers.py` is allowed to contain no network code at all.
"""

from __future__ import annotations

from typing import Any, Mapping, get_args

import pytest

pytest.importorskip("fastapi", reason="fastapi is not importable in this environment")

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import deps, routes_meta  # noqa: E402
from backend.api.routes_meta import ModelsView, ProviderView  # noqa: E402
from backend.engine.config import SECRETS  # noqa: E402
from backend.engine.contracts import Unavailable  # noqa: E402
from backend.intelligence import providers as prov  # noqa: E402
from backend.intelligence.base import (  # noqa: E402
    TransportReply,
    TransportTimeout,
    TransportUnreachable,
)

ROUTES_META = routes_meta.__file__


# --- harness ------------------------------------------------------------------


def build_client(tmp_path, monkeypatch, *, name: str = "picker") -> TestClient:
    """A fresh app on its own databases, with no credential anywhere."""
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / f"{name}-api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / f"{name}-config.db"))
    monkeypatch.setenv("REPOSITORY", "sqlite")
    monkeypatch.setenv("CONFIG_STORE", "sqlite")
    monkeypatch.setenv("PIPELINE", "fixture")
    deps.reset_wiring()

    from backend.api.main import create_app

    app = create_app()
    # After create_app, because create_app loads .env; clearing first would be undone, and
    # `secret_for` promotes an env value into the store on first resolution -- so a key in
    # the developer's shell would otherwise decide what "no key configured" means.
    for env_var in SECRETS.values():
        monkeypatch.delenv(env_var, raising=False)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    return build_client(tmp_path, monkeypatch)


class FakeCatalogue:
    """Replays one recorded reply, or raises it. Records what it was asked for."""

    def __init__(self, reply: TransportReply | Exception) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout_s: float
    ) -> TransportReply:
        self.calls.append({"url": url, "headers": dict(headers), "timeout_s": timeout_s})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def serve(client: TestClient, transport: Any) -> None:
    client.app.dependency_overrides[routes_meta.get_catalogue_transport] = lambda: transport


def openrouter_catalogue() -> TransportReply:
    """Recorded from the real unauthenticated catalogue, trimmed to three entries."""
    return TransportReply(
        status=200,
        payload={
            "data": [
                {"id": "vendor-b/model-2", "name": "Model Two", "context_length": 128000},
                {"id": "vendor-a/model-1", "name": "Model One", "context_length": 8192},
                {"id": "vendor-a/model-1:free", "name": "Model One (free)"},
            ]
        },
    )


# --- the provider list: four rows of local data -------------------------------


def test_the_picker_sees_all_four_rows_with_no_key_and_no_network(client: TestClient) -> None:
    response = client.get("/api/providers")
    assert response.status_code == 200
    rows = [ProviderView.model_validate(row) for row in response.json()]
    assert [row.id for row in rows] == ["anthropic", "google", "openai", "openrouter"]
    assert all(not row.key.present for row in rows)
    assert {row.dialect for row in rows} == {"openai", "anthropic"}


def test_each_row_says_whether_its_catalogue_needs_a_key(client: TestClient) -> None:
    """The one False is the bring-your-own-model row, and it is load-bearing."""
    rows = {row["id"]: row for row in client.get("/api/providers").json()}
    assert {pid: row["models_need_key"] for pid, row in rows.items()} == {
        "openai": True,
        "openrouter": False,
        "google": True,
        "anthropic": True,
    }


def test_the_provider_list_never_returns_a_key_or_part_of_one(client: TestClient) -> None:
    secret = "sk-provider-list-must-not-echo-this"
    client.patch("/api/settings", json={"secrets": {"openai_api_key": secret}})
    response = client.get("/api/providers")
    assert secret not in response.text
    assert "sk-" not in response.text
    row = next(r for r in response.json() if r["id"] == "openai")
    # Presence and provenance, which is the honest report, and no value field to leak.
    assert row["key"]["present"] is True
    assert row["key"]["source"] == "db"
    assert "value" not in row["key"]


def test_a_row_names_the_setting_that_configures_it(client: TestClient) -> None:
    """A name, not a value: it is what lets the Settings page link the two screens."""
    rows = {row["id"]: row for row in client.get("/api/providers").json()}
    assert rows["openrouter"]["secret_id"] in SECRETS
    assert rows["openrouter"]["default_model"] == prov.PROVIDERS["openrouter"].default_model


# --- the catalogue: populated before anyone signs in --------------------------


def test_the_catalogue_that_needs_no_key_answers_with_no_key(client: TestClient) -> None:
    transport = FakeCatalogue(openrouter_catalogue())
    serve(client, transport)

    response = client.get("/api/models", params={"provider": "openrouter"})
    assert response.status_code == 200
    view = ModelsView.model_validate(response.json())
    assert view.unavailable is None
    assert view.key.present is False
    assert [m.id for m in view.models] == [
        "vendor-a/model-1",
        "vendor-a/model-1:free",
        "vendor-b/model-2",
    ]
    assert view.models[0].label == "Model One"
    assert view.models[0].context_length == 8192
    # The fetch happened, against the row's own catalogue path, and with no blank bearer:
    # an empty `Authorization` header is a different request from no header at all, and
    # this is the one row we would be breaking.
    assert transport.calls[0]["url"] == "https://openrouter.ai/api/v1/models"
    assert "authorization" not in transport.calls[0]["headers"]


def test_a_pasted_key_is_sent_to_the_catalogue_but_never_returned(client: TestClient) -> None:
    transport = FakeCatalogue(openrouter_catalogue())
    serve(client, transport)
    client.patch("/api/settings", json={"secrets": {"openrouter_api_key": "sk-byom"}})

    response = client.get("/api/models", params={"provider": "openrouter"})
    assert response.status_code == 200
    assert "sk-byom" not in response.text
    assert transport.calls[0]["headers"]["authorization"] == "Bearer sk-byom"


def test_a_provider_that_needs_a_key_says_no_key_instead_of_guessing(
    client: TestClient,
) -> None:
    transport = FakeCatalogue(openrouter_catalogue())
    serve(client, transport)

    response = client.get("/api/models", params={"provider": "openai"})
    assert response.status_code == 200
    view = ModelsView.model_validate(response.json())
    assert view.unavailable is not None
    assert view.unavailable.reason == "no-key"
    assert view.models == []
    # And nothing was fetched: the one failure knowable before a request exists is
    # answered before a request exists.
    assert transport.calls == []


def test_the_default_model_is_offered_even_when_the_catalogue_is_unreachable(
    client: TestClient,
) -> None:
    """A model we have actually called, so the picker is never empty of choices."""
    serve(client, FakeCatalogue(TransportUnreachable("getaddrinfo failed")))
    view = ModelsView.model_validate(
        client.get("/api/models", params={"provider": "openrouter"}).json()
    )
    assert view.default_model == prov.PROVIDERS["openrouter"].default_model
    assert view.unavailable is not None


# --- every failure is one of the six named states -----------------------------


@pytest.mark.parametrize(
    "reply,expected",
    [
        (TransportReply(status=401, text="invalid api key"), "bad-key"),
        (TransportReply(status=403, text="forbidden"), "bad-key"),
        (TransportReply(status=404, text="not found"), "model-unavailable"),
        (TransportReply(status=429, text="slow down"), "rate-limited"),
        (TransportReply(status=504, text="gateway timeout"), "timeout"),
        (TransportReply(status=503, text="unavailable"), "provider-down"),
        (TransportTimeout("30s elapsed"), "timeout"),
        (TransportUnreachable("tls handshake failed"), "provider-down"),
        (RuntimeError("something nobody predicted"), "provider-down"),
        (TransportReply(status=200, payload={"object": "list"}), "provider-down"),
    ],
)
def test_every_catalogue_failure_comes_back_as_a_named_state_and_a_200(
    client: TestClient, reply, expected: str
) -> None:
    """Not a 5xx and never a traceback: the picker has to be able to say WHY it is empty.

    The provider list beside it is local data and still correct, so a dead provider must
    not take the page down with it (CLAUDE.md section 6).
    """
    serve(client, FakeCatalogue(reply))
    response = client.get("/api/models", params={"provider": "openrouter"})
    assert response.status_code == 200
    view = ModelsView.model_validate(response.json())
    assert view.unavailable is not None
    assert view.unavailable.reason == expected
    assert view.models == []


def test_a_listed_model_that_cannot_be_called_keeps_its_own_name(client: TestClient) -> None:
    """`model-unavailable` is not a flavour of bad-key: the key works, the model does not.

    A catalogue returns models that 404 for keys issued after a provider's cutoff. Blaming
    the credential sends the operator to re-paste a key that was never the problem.
    """
    serve(client, FakeCatalogue(TransportReply(status=404, text="model_not_found")))
    view = ModelsView.model_validate(
        client.get("/api/models", params={"provider": "openrouter"}).json()
    )
    assert view.unavailable is not None
    assert view.unavailable.reason == "model-unavailable"
    assert view.unavailable.detail and "404" in view.unavailable.detail


def test_no_failure_here_invents_a_state_the_banner_cannot_render() -> None:
    """The reasons this endpoint can report are a subset of the ones already named."""
    assert {state.value for state in prov.FailureState} <= set(
        get_args(Unavailable.model_fields["reason"].annotation)
    )


def test_a_missing_http_library_is_a_named_state_rather_than_a_500(
    client: TestClient,
) -> None:
    """The transport is injected, so no transport is `provider-down`, not an exception."""
    serve(client, None)
    response = client.get("/api/models", params={"provider": "openrouter"})
    assert response.status_code == 200
    view = ModelsView.model_validate(response.json())
    assert view.unavailable is not None
    assert view.unavailable.reason == "provider-down"


# --- the seam, and the id it refuses -----------------------------------------


def test_a_provider_id_no_row_declares_is_a_typed_400(client: TestClient) -> None:
    """The same reasoning as an unknown setting name: a silent drop is worse than a 400."""
    response = client.get("/api/models", params={"provider": "not-a-provider"})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "unknown_provider"
    assert "not-a-provider" in body["detail"]


def test_the_catalogue_fetch_is_injectable_rather_than_hardcoded() -> None:
    """A fake with one `get` satisfies the seam, which is why the suite needs no wifi."""
    assert isinstance(FakeCatalogue(openrouter_catalogue()), routes_meta.CatalogueTransport)


def test_the_route_module_imports_its_http_client_inside_a_function_body() -> None:
    """Same rule as `intelligence.base.httpx_transport`, for the same reason.

    A module-level `import httpx` would make this module -- and the provider list, which is
    local data -- unimportable on a machine without an HTTP library.
    """
    source = open(ROUTES_META, encoding="utf-8").read()
    occurrences = [
        line for line in source.splitlines() if line.strip().startswith("import httpx")
    ]
    assert occurrences, "the real transport stopped importing httpx at all"
    assert all(line.startswith(" ") for line in occurrences), occurrences


def test_the_provider_table_is_read_as_data_and_not_restated_in_the_route() -> None:
    """A second copy of the four rows would be a second thing to get wrong."""
    source = open(ROUTES_META, encoding="utf-8").read()
    for provider_id in prov.PROVIDERS:
        assert f'"{provider_id}"' not in source, (
            f"routes_meta names the provider {provider_id!r} instead of reading the table"
        )
