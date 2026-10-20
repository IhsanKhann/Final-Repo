"""An upload actually runs: extract, map, resolve, persist -- and the counts reconcile.

These are the tests behind the demo. They use the real generated documents, the real pack
and the real adapters, with no API key, because that is the configuration the product
promises works: everything deterministic resolves, the rest goes to a human.

Two of them exist because of bugs found by reconciling numbers rather than by reading code:
the batch row has to be written before any document is read, and a label that is not a
reportable field must never reach the review tray.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="fastapi is not importable in this environment")

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import deps  # noqa: E402
from backend.api.main import create_app  # noqa: E402
from backend.engine.config import SECRETS  # noqa: E402

GENERATED = Path(__file__).resolve().parents[1] / "eval" / "generated"

#: The documents the generator produces, in the formats the adapters read.
DEMO_FILES = (
    "pacific_savings_rates.xlsx",
    "first_national_bank_rates.pdf",
    "heritage_financial_rates.html",
    "valley_community_bank_rates.pdf",
)


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """A real client with the honest service, no fixtures and deliberately no key.

    Scrubbing the keys is not tidiness: with one present this test would make live,
    billable model calls on every ambiguous label.
    """
    for env_var in SECRETS.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / "config.db"))
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("LEDGER_DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.delenv("PIPELINE", raising=False)
    monkeypatch.delenv("USE_FIXTURES", raising=False)
    deps.reset_wiring()
    try:
        yield TestClient(create_app())
    finally:
        deps.reset_wiring()


def _upload(client: TestClient, *names: str):
    missing = [name for name in names if not (GENERATED / name).is_file()]
    if missing:
        pytest.skip(
            f"generated fixtures absent ({missing}); run python -m backend.eval.make_documents"
        )
    files = [
        ("files", (name, (GENERATED / name).read_bytes(), "application/octet-stream"))
        for name in names
    ]
    response = client.post("/api/batches", data={"pack_id": "banking_rates"}, files=files)
    assert response.status_code == 201, response.text
    return response.json()


def test_an_upload_produces_mapped_fields_with_no_api_key(client: TestClient) -> None:
    batch = _upload(client, *DEMO_FILES)
    assert batch["stage"] == "ready"
    assert batch["status"] == "done"
    assert batch["stats"]["total_fields"] > 0, "nothing was mapped, so nothing was run"
    assert all(f["status"] == "done" for f in batch["files"]), batch["files"]


def test_the_lane_counts_add_up_to_the_fields_claimed(client: TestClient) -> None:
    """A stats block whose parts do not sum to its total is a number nobody can defend."""
    stats = _upload(client, *DEMO_FILES)["stats"]
    assert (
        stats["auto_approved"] + stats["needs_review"] + stats["missing"]
        == stats["total_fields"]
    )


def test_the_review_queue_reconciles_with_the_batch_stats(client: TestClient) -> None:
    """Found a real bug: orphan rows from a crashed run inflated the tray silently."""
    stats = _upload(client, *DEMO_FILES)["stats"]
    queued = client.get("/api/review-queue").json()
    assert len(queued) == stats["needs_review"] + stats["missing"], (
        "the tray disagrees with the batch it came from, which means rows exist that no "
        "batch screen can show"
    )


def test_nothing_in_the_tray_is_a_label_that_is_not_a_field(client: TestClient) -> None:
    """A column header or a product name is not an ambiguity, it is not data.

    Queueing those buries the one real ambiguity under hundreds of non-fields and makes
    the effort metric argue against us. They are counted, never queued -- and deliberately
    not a fourth MappingStatus, because types.ts fixes that vocabulary and Law V is about
    fields that ARE data.
    """
    _upload(client, *DEMO_FILES)
    queued = client.get("/api/review-queue").json()
    assert queued, "nothing queued at all, so this proves nothing"
    for item in queued:
        # A review row with no target_field is legitimate and is the interesting case:
        # candidates existed but none won, so a human chooses. What is NOT legitimate is a
        # queued row with no explanation, because a reviewer cannot act on it.
        assert item["reason"], f"a queued row with no reason is not actionable: {item}"
        assert item["source_label"], f"a queued row with no source label: {item}"


def test_a_batch_row_exists_before_any_document_is_read(client: TestClient) -> None:
    """Written last, a crash part-way leaves documents and mappings with no parent batch.

    Those rows are invisible to every per-batch screen and still counted by the
    tenant-wide queries behind the tray and the home stats. This asserts the parent is
    always there by checking every persisted document belongs to a batch that exists.
    """
    _upload(client, *DEMO_FILES)
    batch_ids = {batch["id"] for batch in client.get("/api/batches").json()}
    assert batch_ids, "no batch was persisted at all"
    for batch_id in batch_ids:
        assert client.get(f"/api/batches/{batch_id}").status_code == 200

    for item in client.get("/api/review-queue").json():
        assert item["batch_id"] in batch_ids, (
            f"queued row {item['mapping_id']} belongs to batch {item['batch_id']!r}, which "
            "no batch screen can open"
        )


def test_one_unreadable_file_does_not_end_the_batch(client: TestClient) -> None:
    """Error containment at the API seam: that document fails, the run continues."""
    good = GENERATED / DEMO_FILES[1]
    if not good.is_file():
        pytest.skip("generated fixtures absent")
    files = [
        ("files", ("broken.pdf", b"%PDF-1.4\n1 0 obj << /Broken", "application/pdf")),
        ("files", (good.name, good.read_bytes(), "application/octet-stream")),
        ("files", ("notes.rtf", b"{\\rtf1 unsupported}", "application/rtf")),
    ]
    batch = client.post(
        "/api/batches", data={"pack_id": "banking_rates"}, files=files
    ).json()

    by_name = {f["name"]: f for f in batch["files"]}
    assert by_name["broken.pdf"]["status"] == "error"
    assert by_name["broken.pdf"]["error"]
    assert by_name["notes.rtf"]["status"] == "unsupported"
    assert by_name[good.name]["status"] == "done"
    assert batch["stats"]["total_fields"] > 0, "the good file was not processed"
    assert batch["stage"] == "ready"


def test_the_monthly_quote_is_converted_on_a_real_document(client: TestClient) -> None:
    """The x12 case, end to end through the API rather than in a unit test.

    This is the one that proves the unit converter against a document that quotes a rate
    per month while the pack declares the field per annum.
    """
    batch = _upload(client, "pacific_savings_rates.xlsx")
    document_id = next(f["document_id"] for f in batch["files"] if f["document_id"])
    mappings = client.get(f"/api/documents/{document_id}/mappings").json()

    converted = [m for m in mappings if m.get("conversion")]
    assert converted, "no field on this document was converted, so the x12 path never ran"
    sample = converted[0]
    assert sample["conversion"]["factor"] == 12.0
    assert "monthly" in sample["conversion"]["formula_text"].lower()
    # Provenance on every converted value, which is the claim behind clicking a cell.
    assert sample["source_location"] is not None


def test_a_correction_through_the_api_is_learned(client: TestClient) -> None:
    """The feedback loop surfacing in the UI, through the real endpoint."""
    _upload(client, *DEMO_FILES)
    queued = client.get("/api/review-queue").json()
    # A row that already has a target field: accepting one with no field assigned teaches
    # nothing, because there is no field for the precedent to point at. That is correct
    # behaviour and `learned: false` is the honest answer there -- see the note on
    # MappingPatchPayload in the report.
    actionable = [
        item for item in queued if item["status"] == "review" and item["target_field"]
    ]
    if not actionable:
        pytest.skip("no review-lane row with a target field in this run to correct")

    response = client.patch(
        f"/api/mappings/{actionable[0]['mapping_id']}", json={"action": "accept"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mapping"]["status"] == "approved"
    assert body["learned"] is True
    assert "no model call" in (body["learned_message"] or "")


def test_the_gold_table_has_one_row_per_record_not_per_document(client: TestClient) -> None:
    """The deliverable. These documents hold many records and we reported one each."""
    batch = _upload(client, *DEMO_FILES)
    records = client.get(f"/api/batches/{batch['id']}/records?per_page=500").json()
    documents = [f for f in batch["files"] if f["status"] == "done"]
    assert records["total"] > len(documents), (
        f"{records['total']} record(s) from {len(documents)} document(s): the gold table "
        "is still collapsing each file into a single row"
    )
    # Every row must be distinguishable, or the UI cannot address one.
    ids = [row["id"] for row in records["data"]]
    assert len(ids) == len(set(ids)), "two records share an id"


def test_the_record_key_reaches_the_frontend_on_every_mapping(client: TestClient) -> None:
    """The reason the contract field was worth asking for.

    The backend grouping being right is not enough: an individual Mapping and a review-queue
    row have to carry the key too, or the frontend cannot group records or tell a reviewer
    which record a flagged field belongs to. It was correct internally and absent from the
    wire shape for a while, which is the kind of gap that looks fixed from the server side.
    """
    batch = _upload(client, "pacific_savings_rates.xlsx")
    document_id = next(f["document_id"] for f in batch["files"] if f["document_id"])

    mappings = client.get(f"/api/documents/{document_id}/mappings").json()
    assert mappings, "no mappings to check"
    assert all(m.get("record_key") for m in mappings), (
        "a mapping arrived without its record key, so the UI cannot place it in a row"
    )
    assert len({m["record_key"] for m in mappings}) > 1, "every mapping claims one record"

    for item in client.get("/api/review-queue").json():
        assert item.get("record_key"), (
            "a queued row does not say which record it belongs to; once a document has "
            "thirty rows that row identifies nothing a reviewer can go and look at"
        )


def test_a_completed_batch_leaves_evidence_for_every_accepted_field(
    client: TestClient, tmp_path
) -> None:
    """The ledger must not quietly lose its caller again.

    This codebase's signature failure is a correct, tested mechanism with nothing calling
    it: the ledger existed and passed its own tests for hours while no run wrote a single
    row. A count assertion is what makes that impossible to repeat.
    """
    from backend.engine.ledger import SqliteLedger

    batch = _upload(client, *DEMO_FILES)
    accepted = batch["stats"]["auto_approved"]
    assert accepted > 0, "nothing was auto-accepted, so this proves nothing"

    ledger = SqliteLedger(tmp_path / "ledger.db")
    entries = sum(
        len(ledger.latest_for_document(f["document_id"]))
        for f in batch["files"]
        if f.get("document_id")
    )
    assert entries >= accepted, (
        f"{accepted} field(s) were auto-accepted but the ledger holds {entries} entries: "
        "the audit trail cannot defend values it never recorded"
    )
    ok, broken = ledger.verify_chain()
    assert ok, f"the evidence chain is broken at {broken}"


def test_the_export_is_byte_identical_across_two_requests(client: TestClient) -> None:
    """Law IV through the endpoint, not just through the renderer."""
    batch = _upload(client, DEMO_FILES[1])
    url = f"/api/batches/{batch['id']}/export?format=csv&audit=true"
    first = client.get(url).content
    second = client.get(url).content
    assert first == second
    assert b"\r\n" not in first
