"""Law I: the backbone is deterministic. No model call may appear under backend/engine/.

Not a client, not an import, not "just for the edge case". The engine takes proposals in as
plain data and returns decisions, so that the same input and the same version produce the
same output bit for bit. Without that, the round reports measure nothing and "unit
conversion correctness" becomes a coin toss we cannot defend on stage.

This test uses the AST for imports rather than a substring scan, because engine/config.py
legitimately contains the strings "openai_api_key" and "anthropic_api_key" -- those are
secret identifiers, which is exactly the kind of false positive that gets a guard disabled.
A disabled guard is worse than no guard.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "engine"

#: Top-level packages that mean "a model is being called from here".
FORBIDDEN_IMPORTS = {
    "openai",
    "anthropic",
    "httpx",
    "requests",
    "urllib3",
    "aiohttp",
    "vertexai",
    "langchain",
    "langgraph",
    "litellm",
    "transformers",
}

#: Dotted module names that are model providers, where the ROOT package is not.
#:
#: `google` used to be forbidden wholesale and that was too broad: it failed on
#: `from google.cloud import firestore` in the engine's Firestore config store, which is a
#: database client with no model behind it. Law I is about model calls, not about a vendor
#: -- the engine already talks to sqlite3, and a cloud database is the same concern.
#:
#: Narrowed deliberately rather than by exempting the file, and written down here because a
#: guard that gets quietly special-cased for its first false positive stops being a guard.
#: The inference surfaces under `google` are named explicitly instead.
FORBIDDEN_DOTTED = (
    "google.generativeai",
    "google.genai",
    "google.ai",
    "google.cloud.aiplatform",
    "google.cloud.documentai",
)

#: The intelligence layer proposes; the engine must not reach into it.
FORBIDDEN_MODULE_PREFIXES = ("backend.intelligence", "backend.adapters")

#: Call shapes that are a model request even when the import is hidden.
FORBIDDEN_CALL_PATTERNS = (
    re.compile(r"\.chat\.completions\.create\b"),
    re.compile(r"\.messages\.create\b"),
    re.compile(r"\.responses\.create\b"),
    re.compile(r"\bOpenAI\s*\("),
    re.compile(r"\bAnthropic\s*\("),
    re.compile(r"\bgenerate_content\s*\("),
    re.compile(r"\burlopen\s*\("),
)


def _engine_files() -> list[Path]:
    files = sorted(p for p in ENGINE.rglob("*.py") if p.name != "__init__.py")
    assert files, f"found no engine modules under {ENGINE}; this guard would pass vacuously"
    return files


def test_the_engine_imports_no_model_provider():
    offences: list[str] = []
    for path in _engine_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in FORBIDDEN_IMPORTS or alias.name.startswith(FORBIDDEN_DOTTED):
                        offences.append(f"{path.name}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                # `from google.cloud import aiplatform` names the provider in the alias,
                # not in the module, so both halves are checked.
                imported = [f"{node.module}.{a.name}" for a in node.names]
                if (
                    root in FORBIDDEN_IMPORTS
                    or node.module.startswith(FORBIDDEN_DOTTED)
                    or any(name.startswith(FORBIDDEN_DOTTED) for name in imported)
                ):
                    offences.append(f"{path.name}:{node.lineno} imports from {node.module}")
                if node.module.startswith(FORBIDDEN_MODULE_PREFIXES):
                    offences.append(
                        f"{path.name}:{node.lineno} reaches into {node.module}; the engine "
                        "receives proposals as data, it does not fetch them"
                    )
    assert not offences, "Law I violated -- a model provider reached the backbone:\n" + "\n".join(
        offences
    )


def test_the_engine_constructs_no_model_client():
    offences: list[str] = []
    for path in _engine_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            for pattern in FORBIDDEN_CALL_PATTERNS:
                if pattern.search(code):
                    offences.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offences, "Law I violated -- a model call appears in the backbone:\n" + "\n".join(
        offences
    )


def test_this_guard_can_actually_fail(tmp_path):
    """Positive control. A scanner that cannot fail is decoration, not enforcement."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import openai\n\n\ndef map_field(x):\n    return openai.OpenAI().chat.completions.create()\n",
        encoding="utf-8",
    )

    tree = ast.parse(planted.read_text(encoding="utf-8"))
    found_import = any(
        isinstance(node, ast.Import)
        and any(a.name.split(".")[0] in FORBIDDEN_IMPORTS for a in node.names)
        for node in ast.walk(tree)
    )
    found_call = any(
        pattern.search(planted.read_text(encoding="utf-8"))
        for pattern in FORBIDDEN_CALL_PATTERNS
    )
    assert found_import, "the import scanner missed a planted provider import"
    assert found_call, "the call scanner missed a planted model call"


def test_the_narrowed_google_rule_still_catches_the_inference_surfaces(tmp_path):
    """The other half of narrowing: prove what was kept, not just what was allowed.

    `google` was forbidden wholesale and failed on a Firestore client. Narrowing a guard is
    only safe if the thing it was protecting against is still caught, so this plants both
    an allowed Google import and a forbidden one and asserts the verdict on each.
    """
    def imports_of(source: str) -> list[str]:
        found: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if (
                        alias.name.split(".")[0] in FORBIDDEN_IMPORTS
                        or alias.name.startswith(FORBIDDEN_DOTTED)
                    ):
                        found.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [f"{node.module}.{a.name}" for a in node.names]
                if (
                    node.module.split(".")[0] in FORBIDDEN_IMPORTS
                    or node.module.startswith(FORBIDDEN_DOTTED)
                    or any(n.startswith(FORBIDDEN_DOTTED) for n in imported)
                ):
                    found.append(node.module)
        return found

    # A database client is storage, not inference. The engine already uses sqlite3.
    assert imports_of("from google.cloud import firestore") == []
    assert imports_of("from google.cloud import storage, bigquery") == []

    # Inference surfaces stay forbidden, whichever half of the statement names them.
    assert imports_of("from google.cloud import aiplatform") != []
    assert imports_of("import google.generativeai as genai") != []
    assert imports_of("from google.generativeai import GenerativeModel") != []
    assert imports_of("import vertexai") != []
