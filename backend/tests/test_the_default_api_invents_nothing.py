"""With nothing configured, the API must report no metric rather than a plausible one.

This exists because the failure it guards against was live: `/api/home/stats` served
`mapping_accuracy: 0.91` and `/api/packs` served a pack nobody had written, because the
fixture service was the default and a forgotten environment variable was all it took. A
confident number with nothing behind it is the exact failure this product claims to
prevent, and performing it on stage would end the argument.

No measured accuracy exists until the golden set is confirmed. So the contract these tests
pin is: the default service counts rows or reports zero, it serves the pack that really
governs a run, and the health page says why the zero is there.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi is not importable in this environment")

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import deps  # noqa: E402
from backend.api.main import create_app  # noqa: E402


@pytest.fixture
def default_client(tmp_path, monkeypatch) -> TestClient:
    """A client with nothing configured -- deliberately not setting PIPELINE at all."""
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / "config.db"))
    monkeypatch.delenv("PIPELINE", raising=False)
    monkeypatch.delenv("USE_FIXTURES", raising=False)
    deps.reset_wiring()
    try:
        yield TestClient(create_app())
    finally:
        deps.reset_wiring()


def test_the_default_service_is_not_the_fixture(default_client: TestClient) -> None:
    """The whole point. Forgetting a variable must not reach the fabricated numbers."""
    from backend.api.persisted import PersistedService

    assert isinstance(deps.get_pipeline_service(), PersistedService)


def test_home_reports_no_accuracy_rather_than_a_plausible_one(
    default_client: TestClient,
) -> None:
    body = default_client.get("/api/home/stats").json()
    assert body["mapping_accuracy"] == 0.0
    assert body["mapping_accuracy_delta"] == 0.0


def test_insights_reports_no_runs_rather_than_invented_history(
    default_client: TestClient,
) -> None:
    body = default_client.get("/api/insights").json()
    assert body["runs"] == []
    assert body["mapping_accuracy"] == 0.0
    assert body["feedback_improvement"] == 0.0


def test_the_pack_list_is_the_pack_that_actually_governs_a_run(
    default_client: TestClient,
) -> None:
    """A decorative pack on the Schema page misrepresents which rulebook decided a value."""
    from backend.engine import packs as packs_module

    served = {pack["id"] for pack in default_client.get("/api/packs").json()}
    on_disk = set(packs_module.load_packs())
    assert served == on_disk, (
        "the Schema page is showing packs that are not in backend/packs/, so a reviewer "
        "cannot tell which rulebook governs"
    )


def test_health_says_why_every_accuracy_figure_reads_zero(
    default_client: TestClient,
) -> None:
    """A zero with no explanation reads as a measured failure instead of an absent one."""
    layers = {
        layer["name"]: layer for layer in default_client.get("/api/health").json()["layers"]
    }
    scoring = layers.get("Scoring")
    assert scoring is not None, "health does not report the scoring state at all"
    assert scoring["status"] == "degraded"
    assert "confirmed" in scoring["message"]
    assert "required" in scoring["message"]


def test_a_fresh_install_reports_an_empty_pipeline_rather_than_prior_work(
    default_client: TestClient,
) -> None:
    layers = {
        layer["name"]: layer for layer in default_client.get("/api/health").json()["layers"]
    }
    assert "no run has produced a mapping yet" in layers["Pipeline"]["message"]
    assert default_client.get("/api/review-queue").json() == []
    assert default_client.get("/api/batches").json() == []


def test_the_fixture_is_still_reachable_when_asked_for_by_name(
    tmp_path, monkeypatch
) -> None:
    """Gated, not deleted: the fixture is how the frontend is driven before a real run."""
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / "fx-api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / "fx-config.db"))
    monkeypatch.setenv("USE_FIXTURES", "1")
    deps.reset_wiring()
    try:
        from backend.api.fixtures import FixtureService

        assert isinstance(deps.get_pipeline_service(), FixtureService)
    finally:
        deps.reset_wiring()
