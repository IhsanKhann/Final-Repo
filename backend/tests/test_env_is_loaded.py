"""Every entry point that can reach the config layer calls load_env(), and no library does.

The failure this prevents is silent and expensive: a valid key sits in a .env file that
nothing reads, every agent reports `no-key`, the Health page looks plausible because it is
honestly reporting `unset`, and an hour goes into the provider instead of the loader. The
mirror-image failure is just as bad -- a library that loads dotenv on import makes a key's
presence depend on import order -- so both directions are asserted here.

Entry points are found by READING SOURCE, not by importing and hoping: importing a module
to see whether it would have loaded the environment is the one method that cannot
distinguish "did not call it" from "called it and the file was missing".

An entry point is a module that is executed (`if __name__ == "__main__"`) or served
(declares a module-level ASGI `app`). It is required to call `load_env()` only if it can
reach the config layer -- itself or through any `backend.*` module it imports, transitively.
A fixture generator that never resolves a control or a secret has nothing to load, and
demanding the call there would be cargo cult; the moment it starts resolving config, the
transitive check here turns red.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"

#: Touching any of these means the module's behaviour depends on the process environment,
#: which is exactly when an unloaded .env becomes an invisible wrong answer.
CONFIG_TOUCHING = (
    "secret_for(",
    "control(",
    "make_store(",
    "os.environ",
    "os.getenv",
    "getenv(",
)


def _modules() -> dict[str, Path]:
    """Every importable module under backend/, by dotted name. Tests excluded."""
    found: dict[str, Path] = {}
    for path in BACKEND.rglob("*.py"):
        if "__pycache__" in path.parts or "tests" in path.relative_to(BACKEND).parts:
            continue
        rel = path.relative_to(REPO_ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        found[".".join(parts)] = path
    return found


MODULES = _modules()
SOURCES = {name: path.read_text(encoding="utf-8") for name, path in MODULES.items()}


def _tree(name: str) -> ast.Module | None:
    try:
        return ast.parse(SOURCES[name])
    except SyntaxError:
        return None


def _is_main_guard(node: ast.stmt) -> bool:
    """`if __name__ == "__main__":` at module level."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    left = node.test.left
    return isinstance(left, ast.Name) and left.id == "__name__"


def _declares_asgi_app(name: str) -> bool:
    tree = _tree(name)
    if tree is None or "FastAPI(" not in SOURCES[name]:
        return False
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(isinstance(t, ast.Name) and t.id == "app" for t in targets):
            return True
    return False


def _entry_points() -> list[str]:
    out = []
    for name in sorted(MODULES):
        tree = _tree(name)
        if tree is None:
            continue
        if any(_is_main_guard(node) for node in tree.body) or _declares_asgi_app(name):
            out.append(name)
    return out


ENTRY_POINTS = _entry_points()


def _backend_imports(name: str) -> set[str]:
    tree = _tree(name)
    if tree is None:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend"):
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith("backend"))
    return {m for m in out if m in SOURCES}


def _reaches_config(name: str) -> str | None:
    """The module whose config access this entry point inherits, or None."""
    seen: set[str] = set()
    queue = [name]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        source = SOURCES.get(current, "")
        if any(token in source for token in CONFIG_TOUCHING):
            return current
        queue.extend(_backend_imports(current) - seen)
    return None


def _calls_load_env(name: str) -> bool:
    tree = _tree(name)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "load_env":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "load_env":
            return True
    return False


# --- the assertions -----------------------------------------------------------


def test_the_scan_found_the_entry_points_it_was_meant_to_find() -> None:
    """A positive control. A broken scanner and a clean repo both return zero findings,
    and the wrong one reads as success -- so the scanner has to prove it can see."""
    assert MODULES, "no backend modules were scanned: the path or the filter is wrong"
    assert ENTRY_POINTS, "no entry points were found: the AST detection is broken"
    assert "backend.api.main" in ENTRY_POINTS


def test_the_scanner_can_tell_an_entry_point_from_a_library() -> None:
    """The other half of the control: it must also return False for something."""
    assert "backend.engine.contracts" not in ENTRY_POINTS
    assert "backend.api.deps" not in ENTRY_POINTS


@pytest.mark.parametrize("module", ENTRY_POINTS)
def test_an_entry_point_that_can_reach_config_loads_the_environment(module: str) -> None:
    via = _reaches_config(module)
    if via is None:
        pytest.skip(f"{module} never resolves a control, a secret or os.environ")
    assert _calls_load_env(module), (
        f"{module} is an entry point and reaches the config layer (via {via}) but never "
        "calls load_env(). A valid key in .env would be invisible and every provider "
        "would report no-key."
    )


@pytest.mark.parametrize(
    "module", [m for m in sorted(MODULES) if m not in ENTRY_POINTS and m != "backend.engine.config"]
)
def test_a_library_module_does_not_load_the_environment(module: str) -> None:
    """The mirror-image failure: dotenv on import makes a key depend on import order."""
    assert not _calls_load_env(module), (
        f"{module} is not an entry point but calls load_env(). Only entry points may; a "
        "library that loads dotenv makes a key's presence depend on import order."
    )


def test_the_api_entry_point_loads_every_env_file_the_repo_actually_has() -> None:
    """The bug this file exists for, in its concrete form.

    `config.load_env()` with no argument looks for `<repo>/.env`. This repo's file is at
    `backend/.env`, so a bare `load_env()` would read nothing and the key in it would never
    answer -- which is indistinguishable, from the outside, from not having a key.
    """
    from backend.api.main import load_environment

    present = {
        path.resolve()
        for path in (REPO_ROOT / ".env", BACKEND / ".env")
        if path.exists()
    }
    assert present, "no .env file in the repo: this assertion has nothing to protect"

    loaded = {Path(p).resolve() for p in load_environment()}
    unread = present - loaded
    assert unread == set(), (
        f"these .env files exist and no entry point reads them: {sorted(map(str, unread))}"
    )


def test_a_value_in_the_env_file_is_visible_to_the_resolvers_after_loading(
    tmp_path, monkeypatch
) -> None:
    """End to end on the loader itself: a file on disk becomes a resolved value with a
    source of `env`, not `default`."""
    from backend.engine.config import CONTROLS, SqliteStore, control, load_env

    key = "prompt_version"
    env_var = CONTROLS[key].env_var
    monkeypatch.delenv(env_var, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(f"{env_var}=loaded-from-file\n", encoding="utf-8")
    # load_env reports the files it actually read, so a caller can log which .env answered
    # and a test can tell "loaded nothing" from "loaded something".
    assert load_env(env_file) == [env_file]

    store = SqliteStore(tmp_path / "config.db")
    resolved = control(key, store=store)
    assert resolved.value == "loaded-from-file"
    assert resolved.source.value == "env"


def test_the_app_starts_and_serves_with_no_credential_at_all(tmp_path, monkeypatch) -> None:
    """README section 7: "No API key is needed to start the backend"."""
    pytest.importorskip("fastapi", reason="fastapi is not importable in this environment")
    from fastapi.testclient import TestClient

    from backend.api import deps
    from backend.api.main import create_app
    from backend.engine.config import SECRETS

    monkeypatch.setenv("API_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CONFIG_DB_PATH", str(tmp_path / "config.db"))
    deps.reset_wiring()
    app = create_app()
    for env_var in SECRETS.values():
        monkeypatch.delenv(env_var, raising=False)

    with TestClient(app) as client:
        body = client.get("/api/health").json()
    assert body["overall"] == "degraded"
    assert any("no provider key" in (layer["message"] or "") for layer in body["layers"])
