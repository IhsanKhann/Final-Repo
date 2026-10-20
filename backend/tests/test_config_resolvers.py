"""The two resolvers differ on purpose, and these are the differences that matter.

The failure this file protects against is the expensive silent one: an operator pastes a
new key into the Settings page, a stale value in .env quietly answers instead, and the
Health page still says connected. Env is a SEED for a secret, not a fallback.
"""

from __future__ import annotations

import pytest

from backend.engine.config import (
    CONTROLS,
    SECRETS,
    Source,
    SqliteStore,
    control,
    secret_for,
    set_control,
    set_secret,
)


@pytest.fixture(autouse=True)
def _no_inherited_credentials(monkeypatch):
    """Scrub the real environment so these assertions do not depend on whose laptop runs.

    Without this, a developer with a working OPENAI_API_KEY exported sees `secret_for`
    seed from env and the unset-secret tests fail, while CI with no key sees them pass --
    a test that disagrees with itself by machine teaches nobody anything.
    """
    for env_var in SECRETS.values():
        monkeypatch.delenv(env_var, raising=False)
    for spec in CONTROLS.values():
        monkeypatch.delenv(spec.env_var, raising=False)


@pytest.fixture()
def store(tmp_path):
    return SqliteStore(tmp_path / "config.db")


# --- controls: session -> db -> env -> default --------------------------------


def test_a_control_falls_back_to_its_stated_default(store):
    resolved = control("gate_auto_threshold", store=store)
    assert resolved.value == 0.90
    assert resolved.source is Source.DEFAULT


def test_a_control_prefers_env_over_its_default(store, monkeypatch):
    monkeypatch.setenv("GATE_AUTO_THRESHOLD", "0.95")
    resolved = control("gate_auto_threshold", store=store)
    assert resolved.value == 0.95
    assert resolved.source is Source.ENV


def test_a_control_prefers_the_database_over_env(store, monkeypatch):
    monkeypatch.setenv("GATE_AUTO_THRESHOLD", "0.95")
    set_control("gate_auto_threshold", 0.88, store=store)
    resolved = control("gate_auto_threshold", store=store)
    assert resolved.value == 0.88
    assert resolved.source is Source.DB


def test_a_control_prefers_the_session_over_everything(store, monkeypatch):
    monkeypatch.setenv("GATE_AUTO_THRESHOLD", "0.95")
    set_control("gate_auto_threshold", 0.88, store=store)
    resolved = control("gate_auto_threshold", store=store, session={"gate_auto_threshold": 0.5})
    assert resolved.value == 0.5
    assert resolved.source is Source.SESSION


def test_every_resolved_value_carries_a_source_the_settings_page_can_show(store):
    for key in CONTROLS:
        assert control(key, store=store).source in set(Source)


def test_there_is_no_cache_so_the_next_call_sees_the_new_value(store):
    assert control("model", store=store).source is Source.DEFAULT
    set_control("model", "a-different-model", store=store)
    assert control("model", store=store).value == "a-different-model"
    set_control("model", "changed-again", store=store)
    assert control("model", store=store).value == "changed-again"


def test_an_unknown_control_resolves_to_unset_rather_than_guessing(store):
    resolved = control("a_key_nobody_declared", store=store)
    assert resolved.value is None
    assert resolved.source is Source.UNSET


def test_the_active_pack_id_default_names_no_pack():
    """Law II reaches config: a pack id is a domain noun, so the engine cannot hold one."""
    assert CONTROLS["active_pack_id"].default == ""


# --- secrets: session -> db -> env SEED once, then STOP -----------------------


def test_an_unset_secret_is_unset_rather_than_empty(store):
    resolved = secret_for("openai_api_key", store=store)
    assert resolved.value is None
    assert resolved.source is Source.UNSET


def test_env_seeds_a_secret_once_and_is_labelled_as_a_seed(store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    resolved = secret_for("openai_api_key", store=store)
    assert resolved.value == "sk-from-env"
    assert resolved.source is Source.ENV_SEED
    # The store now owns it.
    assert store.get_secret("demo", "openai_api_key") == "sk-from-env"


def test_after_seeding_the_store_owns_the_secret_and_env_is_never_read_again(
    store, monkeypatch
):
    """The whole point. A stale .env must never answer for a key the operator replaced."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stale-from-env")
    secret_for("openai_api_key", store=store)  # seeds

    set_secret("openai_api_key", "sk-pasted-into-settings", store=store)
    resolved = secret_for("openai_api_key", store=store)
    assert resolved.value == "sk-pasted-into-settings"
    assert resolved.source is Source.DB

    # Even if env changes again, it is not consulted.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-even-newer-stale")
    assert secret_for("openai_api_key", store=store).value == "sk-pasted-into-settings"


def test_an_explicitly_cleared_secret_stays_cleared(store, monkeypatch):
    """A stored "" stops the chain, or clearing a key would be impossible."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    secret_for("openai_api_key", store=store)
    set_secret("openai_api_key", "", store=store)

    resolved = secret_for("openai_api_key", store=store)
    assert resolved.value == ""
    assert resolved.source is Source.DB, "env answered for a key the operator had cleared"


def test_an_explicitly_empty_control_also_stops_the_chain(store, monkeypatch):
    monkeypatch.setenv("MODEL", "from-env")
    set_control("model", "", store=store)
    resolved = control("model", store=store)
    assert resolved.value == ""
    assert resolved.source is Source.DB


def test_a_secret_has_no_default_and_no_last_known_good(store):
    """Last-known-good on a secret would resurrect a key that was just revoked."""
    for secret_id in SECRETS:
        resolved = secret_for(secret_id, store=store)
        assert resolved.source in (Source.UNSET, Source.ENV_SEED, Source.DB)
        assert resolved.source is not Source.LAST_KNOWN_GOOD
        assert resolved.source is not Source.DEFAULT


def test_a_session_secret_is_not_written_to_the_store(store):
    """A session value is for one request; persisting it would outlive its consent."""
    resolved = secret_for("openai_api_key", store=store, session={"openai_api_key": "sk-session"})
    assert resolved.value == "sk-session"
    assert resolved.source is Source.SESSION
    assert store.get_secret("demo", "openai_api_key") is None


def test_tenant_id_is_honoured_everywhere_so_auth_costs_one_middleware_later(store):
    set_control("model", "tenant-a-model", store=store, tenant_id="tenant-a")
    set_control("model", "tenant-b-model", store=store, tenant_id="tenant-b")
    assert control("model", store=store, tenant_id="tenant-a").value == "tenant-a-model"
    assert control("model", store=store, tenant_id="tenant-b").value == "tenant-b-model"
    assert control("model", store=store, tenant_id="demo").source is Source.DEFAULT
