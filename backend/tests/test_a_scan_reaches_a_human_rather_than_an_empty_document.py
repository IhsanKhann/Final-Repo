"""A scanned page ends up in front of a person, not reported as a document with nothing on it.

`adapters/pdf_scan.py` was written, tested and unreachable: both PDF adapters claim
application/pdf, the dispatch table holds only the text one, and nothing made the choice
between them -- so the scanned fixture went through the text reader, which succeeded and
found no words, and the batch reported a file that was processed and simply had nothing in
it. That is the single worst outcome in this product, because it is indistinguishable from
a document that really is empty.

What these tests pin, and the ceiling they are careful not to overstate: **no vision call
is made anywhere in this build.** Routing does not make the scan readable. What it makes
true is that the document is rasterized, comes back with a named `Unavailable`, and reaches
the review tray with that reason attached -- which is the honest outcome and a far better
one than a silent zero. A test here that asserted values had been read off the scan would
be asserting a capability that does not exist.

The other half is the discriminator itself. It has to fire for a page of pixels and stay
out of the way for everything else, so there is a test for each direction: a text PDF still
maps, and a corrupt PDF stays an error rather than being handed to the rasterizer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="fastapi is not importable in this environment")

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import deps  # noqa: E402
from backend.api.main import create_app  # noqa: E402
from backend.engine import packs as packs_module  # noqa: E402
from backend.engine.config import SECRETS, SqliteStore, set_secret  # noqa: E402

GENERATED = Path(__file__).resolve().parents[1] / "eval" / "generated"

SCAN = "metro_credit_union_rates_scan.pdf"
TEXT_PDF = "first_national_bank_rates.pdf"

#: The pack the generated documents are written against. Named rather than discovered
#: because a second pack landing in packs/ makes the loader refuse to guess which rulebook
#: governs, and which pack is active is not what any of these tests is about.
WANTED_PACK = "banking_rates"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """A real client with the honest service, and a deliberately absent key.

    The key is stored EMPTY rather than merely unset. `main.py` loads backend/.env at
    startup, so deleting the environment variable hands the key straight back -- and then
    every ambiguous label in these fixtures would make a live, billable call. An explicit
    empty value is a value and stops the chain, which is config.py's own rule used for
    exactly what it is for.
    """
    for env_var in SECRETS.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / "config.db"))
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("LEDGER_DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.delenv("PIPELINE", raising=False)
    monkeypatch.delenv("USE_FIXTURES", raising=False)

    loaded = packs_module.load_packs()
    chosen = WANTED_PACK if WANTED_PACK in loaded else (sorted(loaded)[0] if loaded else "")
    if chosen:
        monkeypatch.setenv("ACTIVE_PACK_ID", chosen)

    store = SqliteStore(tmp_path / "config.db")
    for secret_id in SECRETS:
        set_secret(secret_id, "", store=store)

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
    response = client.post("/api/batches", data={"pack_id": WANTED_PACK}, files=files)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_scanned_pdf_is_rasterized_and_queued_instead_of_reporting_nothing(
    client: TestClient,
) -> None:
    batch = _upload(client, SCAN)
    entry = next(f for f in batch["files"] if f["name"] == SCAN)

    # Not `done`. A document reported done with no fields is the silence the three lanes
    # exist to prevent, and that is what this file used to produce.
    assert entry["status"] != "done", (
        "the scan is being reported as a processed document again, which reads exactly "
        "like a document that was genuinely empty"
    )
    assert entry["error"], "a document nothing could be read from must say why"
    assert "rasteriz" in entry["error"], (
        f"the scan route did not run: {entry['error']!r} is the text adapter's story, not "
        "the rasterizer's"
    )

    # Rasterization really happened, which is what reaching the scan adapter buys.
    document = client.get(f"/api/documents/{entry['document_id']}").json()
    assert document["page_count"] == 2, document

    queued = [
        item
        for item in client.get("/api/review-queue").json()
        if item["document_id"] == entry["document_id"]
    ]
    assert queued, (
        "the scan produced no row a person can see. `Unavailable` routes to review; a "
        "document we could not read must reach a human, not a count of zero"
    )
    for item in queued:
        assert item["status"] == "review", item
        assert item["reason"], "a queued row with no reason is not actionable"
        assert item["source_label"], "a queued row with no source label is not actionable"
        # The ceiling, asserted rather than assumed: nothing was read off the page, so the
        # row claims no field and no value. If this ever stops being true it is because a
        # real vision backend was wired in, and this test should be the thing that says so.
        assert not item["target_field"], (
            "this row names a field, which would mean something read the scan -- no vision "
            "call exists in this build"
        )


def test_the_named_reason_travels_to_the_reviewer(client: TestClient) -> None:
    """`no-key` and `provider-down` are different facts and the tray must say which.

    A generic "could not read it" is the failure mode CLAUDE.md section 5 names: every
    error state is its own named state, and the one a reviewer sees here decides whether
    they wait for a key or chase an outage.
    """
    batch = _upload(client, SCAN)
    entry = next(f for f in batch["files"] if f["name"] == SCAN)
    queued = next(
        item
        for item in client.get("/api/review-queue").json()
        if item["document_id"] == entry["document_id"]
    )
    assert "no-key" in queued["reason"], (
        f"with no key stored the honest named reason is no-key: {queued['reason']!r}"
    )


def test_a_text_pdf_is_left_to_the_text_adapter(client: TestClient) -> None:
    """The discriminator must stay out of the way of the format it is not for."""
    batch = _upload(client, TEXT_PDF)
    entry = next(f for f in batch["files"] if f["name"] == TEXT_PDF)
    assert entry["status"] == "done", entry
    assert batch["stats"]["total_fields"] > 0, "the text PDF stopped being read"
    mappings = client.get(f"/api/documents/{entry['document_id']}/mappings").json()
    assert any(m["source_location"] for m in mappings), "provenance was lost on the way"


def test_a_corrupt_pdf_stays_an_error_and_is_never_handed_to_the_rasterizer(
    client: TestClient,
) -> None:
    """Zero pages and zero facts are different claims, and only one of them is a scan.

    A damaged PDF opens in PyMuPDF with no pages instead of raising, which used to read as
    "processed, nothing in it" -- the same shape as a real scan. Both PDF adapters now
    treat zero pages as an error, and that is what makes the discriminator a fact rather
    than a heuristic. If this goes red, the discriminator is routing broken files into the
    rasterizer and calling the result a review row.
    """
    response = client.post(
        "/api/batches",
        data={"pack_id": WANTED_PACK},
        files=[("files", ("broken.pdf", b"%PDF-1.4\n1 0 obj << /Broken", "application/pdf"))],
    )
    entry = next(f for f in response.json()["files"] if f["name"] == "broken.pdf")
    assert entry["status"] == "error", entry
    assert "rasteriz" not in (entry["error"] or ""), entry
    queued = [
        item
        for item in client.get("/api/review-queue").json()
        if item["document_id"] == entry["document_id"]
    ]
    assert not queued, "a file that would not parse is an error, not something to review"
