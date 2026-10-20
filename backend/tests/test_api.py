"""Every endpoint answers, and its body validates against the contract.

These tests are named for the behaviour they protect, not the handler they call, because
the thing worth protecting is not "the route exists" -- it is that the body matches
`Frontend/src/api/types.ts`, that provenance is never absent, that a secret is never
echoed, that the export is byte-identical, and that a missing row is a typed 404 rather
than a traceback.

Isolation: every client gets its own SQLite files under tmp_path, so no test can see
another's writes and none can touch the developer's real `backend/.data/`. That matters
more than usual here -- `secret_for` PROMOTES an env value into the store on first
resolution, so a shared database would make "no key configured" depend on test order.
"""

from __future__ import annotations

import csv
import io
import json

import pytest

# The whole module is guarded rather than faking a pass: with no network, an environment
# without fastapi must skip loudly, not report green.
pytest.importorskip("fastapi", reason="fastapi is not importable in this environment")

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import deps  # noqa: E402
from backend.api.deps import PipelineService  # noqa: E402
from backend.api.eventlog import RepositoryEventLog, new_event  # noqa: E402
from backend.api.repository import SqliteRepository  # noqa: E402
from backend.api.settings import SettingsView  # noqa: E402
from backend.engine.config import SECRETS  # noqa: E402
from backend.engine.contracts import (  # noqa: E402
    AgentEvent,
    Batch,
    BulkAcceptResponse,
    DatasetRecord,
    Document,
    HealthStatus,
    HomeStats,
    Insights,
    Mapping,
    MappingPatchResponse,
    PaginatedResponse,
    ReviewQueueItem,
    SchemaPack,
    STATUSES_REQUIRING_PROVENANCE,
)

SEEDED_BATCH = "batch-001"
SEEDED_DOCUMENT = "doc-001"
REVIEW_MAPPING = "m2"  # the middle lane, which is the interesting one


# --- harness ------------------------------------------------------------------


def build_client(tmp_path, monkeypatch, *, clear_keys: bool = True, name: str = "t") -> TestClient:
    """A fresh app on its own databases. `clear_keys` makes "no key configured" reliable."""
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / f"{name}-api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / f"{name}-config.db"))
    monkeypatch.setenv("REPOSITORY", "sqlite")
    monkeypatch.setenv("CONFIG_STORE", "sqlite")
    monkeypatch.setenv("PIPELINE", "fixture")
    deps.reset_wiring()

    from backend.api.main import create_app

    app = create_app()
    if clear_keys:
        # After create_app, because create_app loads .env; clearing first would be undone.
        for env_var in SECRETS.values():
            monkeypatch.delenv(env_var, raising=False)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    return build_client(tmp_path, monkeypatch)


def _sources(health: dict) -> list[str]:
    return [layer.get("message") or "" for layer in health["layers"]]


# --- health: block 1's done condition -----------------------------------------


def test_health_answers_without_any_credential_configured(client: TestClient) -> None:
    """README section 7: "No API key is needed to start the backend"."""
    response = client.get("/api/health")
    assert response.status_code == 200
    HealthStatus.model_validate(response.json())


def test_health_names_a_source_for_every_value(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["layers"], "health with no layers tells an operator nothing"
    missing = [layer["name"] for layer in body["layers"] if "source=" not in (layer["message"] or "")]
    assert missing == [], f"these layers report a value with no provenance: {missing}"


def test_health_reports_every_declared_secret_and_control(client: TestClient) -> None:
    """A key absent from the page is indistinguishable from a key that is set."""
    from backend.engine.config import CONTROLS

    names = {layer["name"] for layer in client.get("/api/health").json()["layers"]}
    assert CONTROLS.keys() <= names
    assert len(names) >= len(CONTROLS) + len(SECRETS)


def test_health_is_degraded_with_a_reason_when_no_key_is_configured(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["overall"] == "degraded"
    inference = next(layer for layer in body["layers"] if layer["name"] == "Inference")
    assert inference["status"] == "degraded"
    assert "no provider key" in inference["message"]
    assert "source=unset" in inference["message"]


def test_health_never_returns_a_key_value(client: TestClient) -> None:
    secret = "sk-test-do-not-echo-0123456789"
    client.patch("/api/settings", json={"secrets": {"openai_api_key": secret}})
    body = client.get("/api/health")
    assert secret not in body.text
    layer = next(layer for layer in body.json()["layers"] if layer["name"] == "OpenAI key")
    assert layer["status"] == "ok"
    assert layer["message"] == "key present | source=db"


def test_health_says_where_a_key_came_from_not_just_that_it_exists(client: TestClient) -> None:
    before = client.get("/api/health").json()
    layer_before = next(x for x in before["layers"] if x["name"] == "OpenAI key")
    assert "source=unset" in layer_before["message"]

    client.patch("/api/settings", json={"secrets": {"openai_api_key": "sk-live"}})

    after = client.get("/api/health").json()
    layer_after = next(x for x in after["layers"] if x["name"] == "OpenAI key")
    assert "source=db" in layer_after["message"]


def test_health_is_live_and_not_cached(client: TestClient) -> None:
    first = client.get("/api/health").json()
    client.patch("/api/settings", json={"secrets": {"openai_api_key": "sk-live"}})
    second = client.get("/api/health").json()
    assert first["overall"] == "degraded"
    assert second["overall"] != "degraded" or "Pipeline" in {
        layer["name"] for layer in second["layers"] if layer["status"] == "degraded"
    }
    assert first["checked_at"] != second["checked_at"]


def test_health_admits_the_pipeline_is_a_fixture(client: TestClient) -> None:
    """A fixture that reported `ok` would let somebody demo it believing it processed."""
    layer = next(x for x in client.get("/api/health").json()["layers"] if x["name"] == "Pipeline")
    assert layer["status"] == "degraded"
    assert "fixture" in layer["message"]


# --- settings -----------------------------------------------------------------


def test_settings_reports_a_source_for_every_value(client: TestClient) -> None:
    view = SettingsView.model_validate(client.get("/api/settings").json())
    assert view.controls and view.secrets
    assert all(control.source for control in view.controls)
    assert all(secret.source for secret in view.secrets)


def test_settings_never_echoes_a_secret_value(client: TestClient) -> None:
    secret = "sk-never-echo-abcdef"
    response = client.patch("/api/settings", json={"secrets": {"openai_api_key": secret}})
    assert response.status_code == 200
    assert secret not in response.text
    view = SettingsView.model_validate(response.json())
    entry = next(s for s in view.secrets if s.id == "openai_api_key")
    assert entry.present is True
    assert entry.source == "db"
    assert "value" not in entry.model_dump()


def test_a_secret_patch_goes_to_the_secret_store_not_the_control_store(
    client: TestClient,
) -> None:
    """The two resolvers differ: env is a fallback for a control and a seed for a secret.

    A key written into the control table would let a stale .env answer for it forever.
    """
    client.patch("/api/settings", json={"secrets": {"openai_api_key": "sk-routed"}})
    store = deps.get_config_store()
    assert store.get_secret("demo", "openai_api_key") == "sk-routed"
    assert store.get_control("demo", "openai_api_key") is None


def test_a_control_patch_goes_to_the_control_store_and_reports_its_new_source(
    client: TestClient,
) -> None:
    response = client.patch("/api/settings", json={"controls": {"max_tokens": 2048}})
    view = SettingsView.model_validate(response.json())
    entry = next(c for c in view.controls if c.key == "max_tokens")
    assert entry.value == 2048
    assert entry.source == "db"
    assert deps.get_config_store().get_secret("demo", "max_tokens") is None


def test_clearing_a_secret_is_reported_as_absent_and_still_sourced_from_the_store(
    client: TestClient,
) -> None:
    """An explicit empty value is a value, and it is an absent key."""
    client.patch("/api/settings", json={"secrets": {"openai_api_key": "sk-live"}})
    response = client.patch("/api/settings", json={"secrets": {"openai_api_key": ""}})
    entry = next(
        s for s in SettingsView.model_validate(response.json()).secrets
        if s.id == "openai_api_key"
    )
    assert entry.present is False
    assert entry.source == "db"


def test_settings_refuses_a_name_it_cannot_route(client: TestClient) -> None:
    response = client.patch("/api/settings", json={"controls": {"not_a_control": 1}})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "unknown_setting"
    assert "controls.not_a_control" in body["detail"]


def test_a_refused_settings_patch_writes_nothing(client: TestClient) -> None:
    client.patch("/api/settings", json={"controls": {"max_tokens": 99, "nope": 1}})
    assert deps.get_config_store().get_control("demo", "max_tokens") is None


# --- home and insights --------------------------------------------------------


def test_home_stats_validates_against_the_contract(client: TestClient) -> None:
    response = client.get("/api/home/stats")
    assert response.status_code == 200
    stats = HomeStats.model_validate(response.json())
    assert 0.0 <= stats.auto_approved_pct <= 1.0
    assert stats.recent_batches


def test_insights_validates_against_the_contract(client: TestClient) -> None:
    response = client.get("/api/insights")
    assert response.status_code == 200
    assert Insights.model_validate(response.json()).runs


def test_a_correction_becomes_a_learned_correction_in_insights(client: TestClient) -> None:
    before = Insights.model_validate(client.get("/api/insights").json())
    client.patch(f"/api/mappings/{REVIEW_MAPPING}", json={"action": "accept"})
    after = Insights.model_validate(client.get("/api/insights").json())
    assert len(after.learned_corrections) == len(before.learned_corrections) + 1


# --- batches ------------------------------------------------------------------


def test_batches_list_validates_against_the_contract(client: TestClient) -> None:
    response = client.get("/api/batches")
    assert response.status_code == 200
    batches = [Batch.model_validate(b) for b in response.json()]
    assert {b.id for b in batches} >= {SEEDED_BATCH}


def test_a_single_batch_validates_against_the_contract(client: TestClient) -> None:
    response = client.get(f"/api/batches/{SEEDED_BATCH}")
    assert response.status_code == 200
    assert Batch.model_validate(response.json()).files


def test_creating_a_batch_accepts_the_multipart_form_the_ui_sends(client: TestClient) -> None:
    """client.ts posts FormData: pack_id, optional url, repeated files."""
    response = client.post(
        "/api/batches",
        data={"pack_id": "mining-v1"},
        files=[
            ("files", ("a.csv", b"col\n1\n", "text/csv")),
            ("files", ("b.csv", b"col\n2\n", "text/csv")),
        ],
    )
    assert response.status_code == 201
    batch = Batch.model_validate(response.json())
    assert [f.name for f in batch.files] == ["a.csv", "b.csv"]
    assert batch.pack_id == "mining-v1"


def test_creating_a_batch_also_accepts_a_json_body(client: TestClient) -> None:
    response = client.post("/api/batches", json={"pack_id": "mining-v1"})
    assert response.status_code == 201
    assert Batch.model_validate(response.json()).files == []


def test_creating_a_batch_without_a_pack_is_a_typed_422(client: TestClient) -> None:
    response = client.post("/api/batches", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_payload"


def test_a_created_batch_does_not_claim_its_documents_are_processed(
    client: TestClient,
) -> None:
    """With no pipeline wired, `ready`/`done` would be a lie the demo would repeat."""
    batch = Batch.model_validate(
        client.post("/api/batches", json={"pack_id": "mining-v1"}).json()
    )
    assert batch.stage == "uploading"
    assert batch.status == "pending"


def test_a_missing_batch_is_a_typed_404_not_a_traceback(client: TestClient) -> None:
    response = client.get("/api/batches/no-such-batch")
    assert response.status_code == 404
    body = response.json()
    assert body == {
        "detail": "batch 'no-such-batch' not found",
        "code": "not_found",
        "resource": "batch",
        "id": "no-such-batch",
    }
    assert "Traceback" not in response.text


def test_cancelling_a_running_batch_returns_the_cancelled_batch(client: TestClient) -> None:
    running = next(
        b for b in client.get("/api/batches").json() if b["status"] == "running"
    )
    response = client.post(f"/api/batches/{running['id']}/cancel")
    assert response.status_code == 200
    assert Batch.model_validate(response.json()).status == "cancelled"


def test_cancelling_a_finished_batch_is_a_no_op_rather_than_an_error(
    client: TestClient,
) -> None:
    response = client.post(f"/api/batches/{SEEDED_BATCH}/cancel")
    assert response.status_code == 200
    assert Batch.model_validate(response.json()).status == "done"


def test_cancelling_a_missing_batch_is_a_clean_404(client: TestClient) -> None:
    assert client.post("/api/batches/nope/cancel").status_code == 404


# --- events: the SSE seam -----------------------------------------------------


def test_batch_events_carry_exactly_the_shape_an_sse_frame_would(client: TestClient) -> None:
    response = client.get(f"/api/batches/{SEEDED_BATCH}/events")
    assert response.status_code == 200
    events = [AgentEvent.model_validate(e) for e in response.json()]
    assert events, "an empty log means nothing was written on day one"
    # Identical shape on both sides of the swap: this is the SSE payload, verbatim.
    assert json.loads(events[0].model_dump_json()).keys() == {
        "id", "agent", "step", "status", "message", "timestamp", "file_id"
    }


def test_events_are_written_for_a_batch_created_through_the_api(client: TestClient) -> None:
    batch_id = client.post("/api/batches", json={"pack_id": "mining-v1"}).json()["id"]
    events = client.get(f"/api/batches/{batch_id}/events").json()
    assert [AgentEvent.model_validate(e) for e in events]
    assert any(e["step"] == "ingest" for e in events)


def test_events_resume_from_a_cursor_so_sse_need_not_replay(client: TestClient) -> None:
    all_events = client.get(f"/api/batches/{SEEDED_BATCH}/events").json()
    assert len(all_events) > 1
    tail = client.get(f"/api/batches/{SEEDED_BATCH}/events?after_seq=1").json()
    assert len(tail) == len(all_events) - 1
    assert tail[0]["id"] == all_events[1]["id"]


def test_events_for_a_missing_batch_are_a_clean_404(client: TestClient) -> None:
    assert client.get("/api/batches/nope/events").status_code == 404


# --- records: the pagination envelope -----------------------------------------


def test_records_come_back_in_the_pagination_envelope(client: TestClient) -> None:
    response = client.get(f"/api/batches/{SEEDED_BATCH}/records?page=1&per_page=50")
    assert response.status_code == 200
    page = PaginatedResponse[DatasetRecord].model_validate(response.json())
    assert page.page == 1
    assert page.per_page == 50
    assert page.total == len(page.data)
    assert page.data


def test_a_record_keeps_the_underscore_prefixed_keys_the_ui_reads(client: TestClient) -> None:
    rows = client.get(f"/api/batches/{SEEDED_BATCH}/records").json()["data"]
    assert "_status" in rows[0]
    assert any("_source_page" in row for row in rows)
    # The mapped field names come from the pack, so there must be more than the fixed keys.
    assert set(rows[0]) - {"id", "document_id", "document_name", "_status",
                           "_source_page", "_source_cell"}


def test_pagination_reports_the_unpaged_total_not_the_page_length(client: TestClient) -> None:
    page = PaginatedResponse[DatasetRecord].model_validate(
        client.get(f"/api/batches/{SEEDED_BATCH}/records?page=1&per_page=1").json()
    )
    assert len(page.data) == 1
    assert page.total > 1


def test_a_page_past_the_end_is_empty_rather_than_an_error(client: TestClient) -> None:
    page = PaginatedResponse[DatasetRecord].model_validate(
        client.get(f"/api/batches/{SEEDED_BATCH}/records?page=99&per_page=50").json()
    )
    assert page.data == []
    assert page.total > 0


def test_records_for_a_missing_batch_are_a_clean_404(client: TestClient) -> None:
    assert client.get("/api/batches/nope/records").status_code == 404


# --- export: a file, and the same bytes twice ---------------------------------


def test_the_csv_export_is_a_downloadable_file(client: TestClient) -> None:
    response = client.get(f"/api/batches/{SEEDED_BATCH}/export?format=csv&audit=false")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f'filename="{SEEDED_BATCH}.csv"' in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows
    assert {"id", "document_id", "document_name", "_status"} <= set(rows[0])


def test_the_json_export_is_a_downloadable_file_of_dataset_records(
    client: TestClient,
) -> None:
    response = client.get(f"/api/batches/{SEEDED_BATCH}/export?format=json&audit=false")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert f'filename="{SEEDED_BATCH}.json"' in response.headers["content-disposition"]
    rows = json.loads(response.content)
    assert [DatasetRecord.model_validate(row) for row in rows]


def test_the_export_is_byte_identical_for_the_same_data(client: TestClient) -> None:
    """Law IV: the export is a render, not a generation."""
    url = f"/api/batches/{SEEDED_BATCH}/export?format=csv&audit=true"
    assert client.get(url).content == client.get(url).content
    url_json = f"/api/batches/{SEEDED_BATCH}/export?format=json&audit=false"
    assert client.get(url_json).content == client.get(url_json).content


def test_the_audit_export_adds_provenance_columns_without_changing_values(
    client: TestClient,
) -> None:
    plain = list(csv.DictReader(io.StringIO(
        client.get(f"/api/batches/{SEEDED_BATCH}/export?format=csv&audit=false").text
    )))
    audited = list(csv.DictReader(io.StringIO(
        client.get(f"/api/batches/{SEEDED_BATCH}/export?format=csv&audit=true").text
    )))
    assert set(audited[0]) - set(plain[0]) == {"_source_page", "_source_cell"}
    for before, after in zip(plain, audited):
        assert {k: after[k] for k in before} == before


def test_the_export_refuses_a_format_it_cannot_render(client: TestClient) -> None:
    assert client.get(f"/api/batches/{SEEDED_BATCH}/export?format=xml").status_code == 422


def test_the_export_for_a_missing_batch_is_a_clean_404(client: TestClient) -> None:
    assert client.get("/api/batches/nope/export?format=csv").status_code == 404


# --- documents and mappings ---------------------------------------------------


def test_a_document_validates_against_the_contract(client: TestClient) -> None:
    response = client.get(f"/api/documents/{SEEDED_DOCUMENT}")
    assert response.status_code == 200
    Document.model_validate(response.json())


def test_a_missing_document_is_a_clean_404(client: TestClient) -> None:
    response = client.get("/api/documents/no-such-doc")
    assert response.status_code == 404
    assert response.json()["resource"] == "document"


def test_document_mappings_validate_against_the_contract(client: TestClient) -> None:
    response = client.get(f"/api/documents/{SEEDED_DOCUMENT}/mappings")
    assert response.status_code == 200
    mappings = [Mapping.model_validate(m) for m in response.json()]
    assert mappings


def test_every_asserted_value_carries_its_source_location(client: TestClient) -> None:
    """CLAUDE.md: a value without provenance must be impossible to construct."""
    mappings = [
        Mapping.model_validate(m)
        for m in client.get(f"/api/documents/{SEEDED_DOCUMENT}/mappings").json()
    ]
    asserted = [m for m in mappings if m.status in STATUSES_REQUIRING_PROVENANCE]
    assert asserted
    assert all(m.source_location is not None for m in asserted)


def test_the_three_lanes_are_all_representable(client: TestClient) -> None:
    """Law V: three states, never two, and the middle one is the interesting case."""
    statuses = {
        m["status"] for m in client.get(f"/api/documents/{SEEDED_DOCUMENT}/mappings").json()
    }
    assert {"auto", "review", "missing"} <= statuses


def test_mappings_for_a_missing_document_are_a_404_not_an_empty_list(
    client: TestClient,
) -> None:
    """An empty drawer and a bad link must not look the same."""
    assert client.get("/api/documents/nope/mappings").status_code == 404


# --- the feedback loop --------------------------------------------------------


def test_accepting_a_reviewed_field_reports_that_it_learned(client: TestClient) -> None:
    response = client.patch(f"/api/mappings/{REVIEW_MAPPING}", json={"action": "accept"})
    assert response.status_code == 200
    result = MappingPatchResponse.model_validate(response.json())
    assert result.mapping.status == "approved"
    assert result.learned is True
    assert result.learned_message


def test_an_edit_replaces_the_value_and_is_persisted(client: TestClient) -> None:
    response = client.patch(
        f"/api/mappings/{REVIEW_MAPPING}",
        json={"action": "edit", "value": "9300", "unit": "$/t", "reason": "excl. royalties"},
    )
    result = MappingPatchResponse.model_validate(response.json())
    assert result.mapping.value == "9300"
    assert result.mapping.reason == "excl. royalties"
    again = client.get(f"/api/documents/{SEEDED_DOCUMENT}/mappings").json()
    assert next(m for m in again if m["id"] == REVIEW_MAPPING)["value"] == "9300"


def test_rejecting_a_field_does_not_claim_it_learned(client: TestClient) -> None:
    """A rejection is not a mapping, so there is no precedent to write."""
    result = MappingPatchResponse.model_validate(
        client.patch(f"/api/mappings/{REVIEW_MAPPING}", json={"action": "reject"}).json()
    )
    assert result.mapping.status == "rejected"
    assert result.learned is False


def test_accepting_an_already_settled_field_does_not_claim_it_learned(
    client: TestClient,
) -> None:
    auto_id = next(
        m["id"]
        for m in client.get(f"/api/documents/{SEEDED_DOCUMENT}/mappings").json()
        if m["status"] == "auto"
    )
    result = MappingPatchResponse.model_validate(
        client.patch(f"/api/mappings/{auto_id}", json={"action": "accept"}).json()
    )
    assert result.learned is False


def test_a_missing_mapping_is_a_clean_404(client: TestClient) -> None:
    response = client.patch("/api/mappings/no-such-mapping", json={"action": "accept"})
    assert response.status_code == 404
    assert response.json()["resource"] == "mapping"


def test_a_mapping_patch_with_an_unknown_action_is_a_typed_422(client: TestClient) -> None:
    response = client.patch(f"/api/mappings/{REVIEW_MAPPING}", json={"action": "maybe"})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_payload"


def test_bulk_accept_takes_only_the_fields_above_the_confidence_floor(
    client: TestClient,
) -> None:
    before = client.get("/api/documents/doc-001/mappings").json()
    high = [m for m in before if m["status"] == "review" and m["confidence"] >= 0.6]
    response = client.post(
        "/api/mappings/bulk-accept", json={"document_id": "doc-001", "min_confidence": 0.6}
    )
    assert response.status_code == 200
    result = BulkAcceptResponse.model_validate(response.json())
    assert result.accepted_count == len(high)
    assert all(m.status == "approved" for m in result.mappings)


def test_bulk_accept_leaves_the_missing_lane_alone(client: TestClient) -> None:
    """`missing` is written and shown, never silently promoted."""
    client.post("/api/mappings/bulk-accept", json={"document_id": "doc-001", "min_confidence": 0.0})
    after = client.get("/api/documents/doc-001/mappings").json()
    assert any(m["status"] == "missing" for m in after)


def test_bulk_accept_for_a_missing_document_is_a_clean_404(client: TestClient) -> None:
    response = client.post(
        "/api/mappings/bulk-accept", json={"document_id": "nope", "min_confidence": 0.5}
    )
    assert response.status_code == 404


def test_the_review_queue_validates_against_the_contract(client: TestClient) -> None:
    response = client.get("/api/review-queue")
    assert response.status_code == 200
    items = [ReviewQueueItem.model_validate(i) for i in response.json()]
    assert items
    assert {i.status for i in items} <= {"review", "missing"}
    assert all(i.document_name for i in items)
    assert all(i.batch_id for i in items)


def test_an_accepted_field_leaves_the_review_queue(client: TestClient) -> None:
    before = {i["mapping_id"] for i in client.get("/api/review-queue").json()}
    assert REVIEW_MAPPING in before
    client.patch(f"/api/mappings/{REVIEW_MAPPING}", json={"action": "accept"})
    after = {i["mapping_id"] for i in client.get("/api/review-queue").json()}
    assert REVIEW_MAPPING not in after


# --- packs --------------------------------------------------------------------


def test_the_pack_list_validates_against_the_contract(client: TestClient) -> None:
    response = client.get("/api/packs")
    assert response.status_code == 200
    packs = [SchemaPack.model_validate(p) for p in response.json()]
    assert packs and packs[0].fields


def test_a_single_pack_validates_against_the_contract(client: TestClient) -> None:
    response = client.get("/api/packs/mining-v1")
    assert response.status_code == 200
    assert SchemaPack.model_validate(response.json()).conversions


def test_a_missing_pack_is_a_clean_404(client: TestClient) -> None:
    assert client.get("/api/packs/nope").status_code == 404
    assert client.put("/api/packs/nope", json={"name": "x"}).status_code == 404


def test_a_partial_pack_update_keeps_the_rest_of_the_pack(client: TestClient) -> None:
    """The UI sends Partial<SchemaPack>; absent keys must not be erased."""
    before = SchemaPack.model_validate(client.get("/api/packs/mining-v1").json())
    response = client.put("/api/packs/mining-v1", json={"description": "edited"})
    assert response.status_code == 200
    after = SchemaPack.model_validate(response.json())
    assert after.description == "edited"
    assert after.fields == before.fields
    assert after.conversions == before.conversions
    assert after.id == before.id


def test_a_pack_update_cannot_change_the_pack_id(client: TestClient) -> None:
    after = SchemaPack.model_validate(
        client.put("/api/packs/mining-v1", json={"id": "hijacked"}).json()
    )
    assert after.id == "mining-v1"


# --- the seams ----------------------------------------------------------------


def test_the_fixture_satisfies_the_pipeline_protocol(client: TestClient) -> None:
    """The engine replaces this object; if the Protocol drifts, this goes red first."""
    assert isinstance(deps.get_pipeline_service(), PipelineService)


def test_a_service_wired_in_through_the_seam_is_the_one_the_routes_use(
    tmp_path, monkeypatch
) -> None:
    """`use_pipeline_service` is the whole handover to the real engine."""
    client = build_client(tmp_path, monkeypatch, name="wire")
    from backend.api.fixtures import FixtureService

    class OneBatchService(FixtureService):
        def list_batches(self, *, tenant_id: str = "demo"):
            return []

    deps.use_pipeline_service(
        OneBatchService(deps.get_repository(), RepositoryEventLog(deps.get_repository()))
    )
    assert client.get("/api/batches").json() == []


def test_the_repository_keeps_tenants_apart(tmp_path) -> None:
    """tenant_id is a column everywhere now, so auth later is one middleware."""
    repo = SqliteRepository(tmp_path / "tenants.db")
    batch = Batch(
        id="b1", name="n", pack_id="p", pack_name="P", files=[], stage="ready",
        status="done", created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )
    repo.upsert_batch(batch, tenant_id="alpha")
    assert repo.get_batch("b1", tenant_id="alpha") is not None
    assert repo.get_batch("b1", tenant_id="beta") is None
    assert repo.list_batches(tenant_id="beta") == []


def test_the_repository_reports_absence_instead_of_raising(tmp_path) -> None:
    repo = SqliteRepository(tmp_path / "absent.db")
    assert repo.get_batch("nope") is None
    assert repo.get_document("nope") is None
    assert repo.get_mapping("nope") is None
    assert repo.list_events("nope") == []
    assert repo.ping()[0] is True


def test_the_event_log_preserves_order_and_resumes_from_a_cursor(tmp_path) -> None:
    log = RepositoryEventLog(SqliteRepository(tmp_path / "events.db"))
    for i in range(3):
        log.emit("b1", new_event("Mapper", "map", "running", f"step {i}"))
    assert [e.message for e in log.read("b1")] == ["step 0", "step 1", "step 2"]
    assert [e.message for e in log.read("b1", after_seq=2)] == ["step 2"]
    assert [e.message for e in log.stream("b1", after_seq=1)] == ["step 1", "step 2"]
    assert log.seq("b1") == 3


def test_an_unexpected_failure_below_the_api_is_a_typed_body_not_a_trace(
    tmp_path, monkeypatch
) -> None:
    """Containment at the outermost seam: the type, never the trace."""
    client = build_client(tmp_path, monkeypatch, name="boom")
    from backend.api.fixtures import FixtureService

    class BrokenService(FixtureService):
        def review_queue(self, *, tenant_id: str = "demo"):
            raise RuntimeError("a layer raised across its seam")

    deps.use_pipeline_service(
        BrokenService(deps.get_repository(), RepositoryEventLog(deps.get_repository()))
    )
    response = client.get("/api/review-queue")
    assert response.status_code == 500
    assert response.json() == {
        "detail": "internal error (RuntimeError)",
        "code": "internal_error",
        "resource": None,
        "id": None,
    }
    assert "Traceback" not in response.text
    assert "seam" not in response.text


def test_every_contracted_path_is_mounted(client: TestClient) -> None:
    """README section 4 lists the paths. Implement exactly those, and all of them."""
    mounted = {
        (route.path, method)
        for route in client.app.routes
        for method in getattr(route, "methods", set())
    }
    expected = {
        ("/api/health", "GET"),
        ("/api/home/stats", "GET"),
        ("/api/batches", "GET"),
        ("/api/batches", "POST"),
        ("/api/batches/{batch_id}", "GET"),
        ("/api/batches/{batch_id}/events", "GET"),
        ("/api/batches/{batch_id}/cancel", "POST"),
        ("/api/batches/{batch_id}/records", "GET"),
        ("/api/batches/{batch_id}/export", "GET"),
        ("/api/documents/{document_id}", "GET"),
        ("/api/documents/{document_id}/mappings", "GET"),
        ("/api/mappings/{mapping_id}", "PATCH"),
        ("/api/mappings/bulk-accept", "POST"),
        ("/api/review-queue", "GET"),
        ("/api/packs", "GET"),
        ("/api/packs/{pack_id}", "GET"),
        ("/api/packs/{pack_id}", "PUT"),
        ("/api/insights", "GET"),
        ("/api/settings", "GET"),
        ("/api/settings", "PATCH"),
    }
    assert expected <= mounted, f"not mounted: {sorted(expected - mounted)}"


def test_the_browser_can_reach_the_api_from_the_vite_dev_server(client: TestClient) -> None:
    """VITE_USE_MOCK=false with no console errors needs the preflight to pass."""
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
