"""The upload cap: a file too big is declined, not parsed, and the batch still runs.

Before this cap existed, `size_bytes=len(content)` was recorded on every upload and
compared with nothing, so a half-gigabyte document was read fully into one `bytes` object
and handed to a parser that would hold it again. The refusal is per FILE, because CLAUDE.md
section 6 is explicit that one bad file never ends a batch -- and the number is a control,
so an operator moves it the way they move a gate threshold rather than editing a constant.

The cap is set to a handful of bytes in these tests on purpose: the behaviour under test is
the comparison and the refusal, and a real 65 MiB fixture would buy nothing but minutes.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi is not importable in this environment")

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import deps, routes_batches  # noqa: E402
from backend.engine.config import CONTROLS, SECRETS  # noqa: E402
from backend.engine.contracts import Batch  # noqa: E402

CAP = routes_batches.UPLOAD_CAP_CONTROL


def build_client(tmp_path, monkeypatch, *, name: str = "cap") -> TestClient:
    monkeypatch.setenv("API_DB_PATH", str(tmp_path / f"{name}-api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / f"{name}-config.db"))
    monkeypatch.setenv("REPOSITORY", "sqlite")
    monkeypatch.setenv("CONFIG_STORE", "sqlite")
    monkeypatch.setenv("PIPELINE", "fixture")
    monkeypatch.delenv(CONTROLS[CAP].env_var, raising=False)
    deps.reset_wiring()

    from backend.api.main import create_app

    app = create_app()
    for env_var in SECRETS.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.delenv(CONTROLS[CAP].env_var, raising=False)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    return build_client(tmp_path, monkeypatch)


def set_cap(client: TestClient, value: int | str) -> None:
    response = client.patch("/api/settings", json={"controls": {CAP: value}})
    assert response.status_code == 200
    assert f"controls.{CAP}" in response.json()["updated"]


def upload(client: TestClient, *files: tuple[str, bytes]) -> dict:
    response = client.post(
        "/api/batches",
        data={"pack_id": "pack-under-test"},
        files=[("files", (name, content, "text/csv")) for name, content in files],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    Batch.model_validate(body)
    return body


def file_named(batch: dict, name: str) -> dict:
    return next(f for f in batch["files"] if f["name"] == name)


# --- the refusal --------------------------------------------------------------


def test_one_oversize_file_is_declined_and_the_rest_of_the_batch_runs(
    client: TestClient,
) -> None:
    set_cap(client, 64)
    batch = upload(client, ("small.csv", b"a,b\n1,2\n"), ("huge.csv", b"x" * 5000))

    assert file_named(batch, "small.csv")["status"] != "unsupported"
    refused = file_named(batch, "huge.csv")
    # `unsupported`, not `error`: nothing went wrong, we declined.
    assert refused["status"] == "unsupported"
    assert refused["size"] == 5000
    assert refused["document_id"] is None


def test_the_reason_names_both_numbers_and_the_setting_that_holds_the_second(
    client: TestClient,
) -> None:
    """A refusal a reviewer cannot act on is a dead end, so the message carries the fix."""
    set_cap(client, 64)
    batch = upload(client, ("huge.csv", b"x" * 1048576))
    error = file_named(batch, "huge.csv")["error"]
    assert "1.0 MiB" in error
    assert "0.0 MiB" in error  # the cap, in the same unit, so the two are comparable
    assert CAP in error


def test_the_declined_file_is_still_counted_among_the_batchs_files(
    client: TestClient,
) -> None:
    """It is a file the uploader sent. Dropping it would make the UI disagree with them."""
    set_cap(client, 64)
    batch = upload(client, ("small.csv", b"a,b\n1,2\n"), ("huge.csv", b"x" * 5000))
    assert len(batch["files"]) == 2
    assert batch["stats"]["total_files"] == 2


def test_a_whole_batch_of_oversize_files_still_produces_a_batch(client: TestClient) -> None:
    """Every file refused is still an answer, with a reason per file -- not a 4xx."""
    set_cap(client, 8)
    batch = upload(client, ("one.csv", b"x" * 100), ("two.csv", b"y" * 200))
    assert [f["status"] for f in batch["files"]] == ["unsupported", "unsupported"]
    assert all(f["error"] for f in batch["files"])


# --- it is declined BEFORE it is materialised ---------------------------------


def test_the_oversize_file_is_never_read_into_memory(
    client: TestClient, monkeypatch
) -> None:
    """The point of the cap, asserted directly rather than inferred from the message.

    `UploadFile.read()` is what turns a spooled part into one `bytes` object the process
    has to hold. Sabotaging it proves the route decided from the size the multipart parser
    had already counted, instead of reading first and measuring after.
    """
    from starlette.datastructures import UploadFile

    def never(*args, **kwargs):
        raise AssertionError("the route read a file it had already decided to refuse")

    set_cap(client, 16)
    monkeypatch.setattr(UploadFile, "read", never)

    batch = upload(client, ("huge.csv", b"x" * 300000))
    assert file_named(batch, "huge.csv")["status"] == "unsupported"


def test_the_service_is_never_handed_the_bytes_of_a_refused_file(
    client: TestClient,
) -> None:
    seen: list[list[str]] = []
    inner = deps.get_pipeline_service()

    class Recording:
        def create_batch(self, payload, files, *, tenant_id="demo"):
            seen.append([f.name for f in files])
            return inner.create_batch(payload, files, tenant_id=tenant_id)

        def __getattr__(self, name):
            return getattr(inner, name)

    deps.use_pipeline_service(Recording())
    try:
        set_cap(client, 64)
        upload(client, ("small.csv", b"a,b\n1,2\n"), ("huge.csv", b"x" * 5000))
    finally:
        deps.use_pipeline_service(inner)

    assert seen == [["small.csv"]]


# --- the cap is a control, with a default that points the safe way -------------


def test_the_cap_is_declared_as_a_control_and_not_a_constant() -> None:
    spec = CONTROLS[CAP]
    assert spec.cast == "int"
    assert spec.default == 64 * 1024 * 1024
    assert spec.env_var == "UPLOAD_MAX_BYTES"


def test_an_operator_can_move_the_cap_without_a_deploy(client: TestClient) -> None:
    """The same demonstration the gate thresholds get: change the setting, rerun, differ."""
    content = b"x" * 5000
    set_cap(client, 64)
    assert file_named(upload(client, ("f.csv", content)), "f.csv")["status"] == "unsupported"

    set_cap(client, 1048576)
    assert file_named(upload(client, ("f.csv", content)), "f.csv")["status"] != "unsupported"


def test_a_file_exactly_at_the_cap_is_accepted(client: TestClient) -> None:
    """The boundary is stated, so nobody has to guess which side of it is refused."""
    set_cap(client, 100)
    batch = upload(client, ("at.csv", b"x" * 100), ("over.csv", b"x" * 101))
    assert file_named(batch, "at.csv")["status"] != "unsupported"
    assert file_named(batch, "over.csv")["status"] == "unsupported"


def test_a_cleared_cap_falls_back_to_the_default_rather_than_meaning_unlimited(
    client: TestClient,
) -> None:
    """A control someone emptied must not silently turn the cap off.

    An explicit empty value is a value everywhere else in the config layer -- here that
    value cannot be honoured, because "" as a byte count would mean no limit at all, which
    is the state the cap exists to prevent. So the declared default answers instead.
    """
    set_cap(client, "")
    store = deps.get_config_store()
    assert routes_batches._cap_bytes(store, "demo") == CONTROLS[CAP].default
    batch = upload(client, ("ordinary.csv", b"a,b\n1,2\n"))
    assert file_named(batch, "ordinary.csv")["status"] != "unsupported"


def test_an_ordinary_upload_is_untouched_by_the_cap(client: TestClient) -> None:
    """The default has to let real documents through, or the guard is a denial of service."""
    batch = upload(client, ("ordinary.csv", b"a,b\n1,2\n"))
    assert len(batch["files"]) == 1
    assert file_named(batch, "ordinary.csv")["status"] != "unsupported"
    assert file_named(batch, "ordinary.csv")["error"] is None
