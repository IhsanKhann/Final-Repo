"""A control an operator can change must actually change something.

This codebase's signature failure is a correct mechanism with nothing calling it. It is on
the record in docs/AGREEMENTS.md section 3 -- `OPENAI_KEY` against `OPENAI_API_KEY`, where
the resolver was right, the suite was green and the caller read a key nobody ever set --
and it has now recurred on the ledger, on the two gate thresholds and on the page
threshold. Every one of those looked identical from the outside: a declaration, a test over
the declaration, and no line of production code joining them.

So this test does not check that the control registry is well formed. It checks that
somewhere outside the registry, something asks for each key by name. A control nobody reads
is worse than a missing feature: the Settings page shows it, /api/settings reports it with
its source, the health screen displays it, and the run ignores it -- the UI asserts
something false, and the only way to find out is to change the value and watch nothing
happen.

What this file refuses to do: it refuses to carry an exemption list. A guard quietly
special-cased for its first false positive stops being a guard, which is how the three
recurrences above got past a green suite. If a control legitimately has no reader yet, this
test is supposed to be red and somebody is supposed to decide about it out loud.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.engine.config import CONTROLS

BACKEND = Path(__file__).resolve().parents[1]

#: The declaration itself. A key appearing in its own ControlSpec is the thing being
#: tested, not evidence about it.
DECLARATION = BACKEND / "engine" / "config.py"

#: A control key that no file reads, used to prove the scanner can still return nothing.
#: A pattern broken by a typo and a genuinely well-wired backend both report zero
#: offences, and the wrong one reads as success -- the same positive-control reasoning
#: Law II's scanner carries.
UNREAD_KEY = "a_control_no_caller_has_ever_heard_of"


def _sources() -> list[Path]:
    """Every production source file. Tests are excluded deliberately.

    A test that resolves a control proves the resolver works, not that the product ever
    asks. Counting tests as readers is exactly how a mechanism with no caller passes.
    """
    return sorted(
        path
        for path in BACKEND.rglob("*.py")
        if path != DECLARATION
        and "tests" not in path.parts
        and "__pycache__" not in path.parts
    )


def _lines() -> list[tuple[str, int, str]]:
    """(path, line number, text) for every line of production source. Read once."""
    out: list[tuple[str, int, str]] = []
    for path in _sources():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:  # a file another lane is moving under us is not a finding
            continue
        name = str(path.relative_to(BACKEND)).replace("\\", "/")
        out.extend(
            (name, lineno, line)
            for lineno, line in enumerate(text.splitlines(), 1)
        )
    return out


def _readers(key: str) -> list[str]:
    """Where something asks for `key`, as "path:line: text".

    Two shapes count, because both are real and in use:

      * the key quoted in a call's first argument -- `control("provider", store=...)`,
        `resolved("temperature")`;
      * the key bound to a module constant that is then passed to a call --
        `UPLOAD_CAP_CONTROL = "upload_max_bytes"` and `control(UPLOAD_CAP_CONTROL, ...)`.
        A constant nobody passes anywhere does NOT count, which is the whole point.

    Matching the call POSITION rather than the bare string is what keeps a coincidence from
    counting: `rounds.py` lists "provider" and "model" as RoundReport field names, and a
    field name that happens to equal a control key resolves nothing.

    A `set_control` line is excluded on purpose. Writing a key is not reading it -- a page
    that stores a value nothing ever resolves is exactly the bug this file exists for.
    """
    quoted = re.compile(rf"""\(\s*["']{re.escape(key)}["']""")
    bound = re.compile(rf"""^\s*([A-Z][A-Z0-9_]*)\s*=\s*["']{re.escape(key)}["']\s*$""")
    lines = _lines()

    found: list[str] = []
    aliases: set[str] = set()
    for path, lineno, line in lines:
        if quoted.search(line) and "set_control" not in line:
            found.append(f"{path}:{lineno}: {line.strip()}")
        alias = bound.match(line)
        if alias is not None:
            aliases.add(alias.group(1))

    for alias in sorted(aliases):
        used = re.compile(rf"\(\s*{re.escape(alias)}\b")
        found.extend(
            f"{path}:{lineno}: {line.strip()}"
            for path, lineno, line in lines
            if used.search(line) and "set_control" not in line
        )
    return found


def test_every_control_is_read_by_something_outside_its_own_declaration():
    orphans = {key: _readers(key) for key in sorted(CONTROLS)}
    unread = sorted(key for key, readers in orphans.items() if not readers)
    assert not unread, (
        "these controls are declared, resolvable, reported by /api/settings and displayed "
        f"on the Settings page, and nothing in the product reads them: {unread}. Either "
        "wire a caller or delete the declaration -- a control the UI asserts and the "
        "pipeline ignores is a false claim with a text box in front of it."
    )


def test_the_scanner_would_notice_a_control_nobody_reads():
    """The positive control. Without it, a broken pattern reads exactly like a clean tree."""
    assert not _readers(UNREAD_KEY), (
        f"{UNREAD_KEY!r} is not read anywhere, so finding a reader for it means the "
        "pattern above matches something other than a resolution"
    )
    # And the pattern does find a real one, so a typo in it cannot pass as a green suite.
    assert _readers("provider"), "the scanner found no reader for a control that has one"
