"""Law II: meaning lives only in the pack. No domain proper noun outside backend/packs/.

The engine must never have heard of the customer's industry. That is what lets us answer
"does it work in another domain?" with a second YAML file and zero code change, and it is
why the pack is the moat rather than the parser.

The positive control is the whole point of this file. A scanner broken by a typo and a
genuinely clean engine both return zero findings, and the wrong one reads as success. So
the same scanner is also run over material that definitely contains the terms, and this
file fails if it does not find them there.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PACKS = BACKEND / "packs"

#: Directories that must stay domain-free. Per CLAUDE.md Law II: engine, adapters, api.
CLEAN_DIRECTORIES = ("engine", "adapters", "api")

#: Domain terms, as whole-word patterns. These name meanings in the customer's industry;
#: every one of them belongs in a pack YAML, which is data.
DOMAIN_TERMS = (
    "apy",
    "annual percentage yield",
    "money market",
    "money_market",
    "rate sheet",
    "rate_sheet",
    "high-yield",
    "high_yield",
    "checking plus",
    "interest rate",
    "min_deposit",
    "minimum deposit",
    "rate_pct",
    "apy_pct",
    "bank",
    "credit union",
    "first national",
    "heritage financial",
    "metro credit",
    "pacific savings",
    "summit trust",
    "valley community",
)

#: eval/ generates fixture documents and therefore must name institutions; memory/ and
#: tests/ are likewise outside Law II's named scope. Listed explicitly so the exemption is
#: a decision on the record rather than an accident of which directories got scanned.
EXEMPT_WITH_REASON = {
    "eval": "generates the fixture documents, so institution names are its subject matter",
    "memory": "stores opaque source labels supplied by the pack and the analyst",
    "tests": "names the terms in order to test for them",
    "packs": "is the one place meaning is allowed to live",
}


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    return [(term, re.compile(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", re.I)) for term in DOMAIN_TERMS]


def _scan(text: str) -> set[str]:
    return {term for term, pattern in _patterns() if pattern.search(text)}


def _files_in(directory: str) -> list[Path]:
    root = BACKEND / directory
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.py") if p.name != "__init__.py")


def test_the_engine_adapters_and_api_name_no_domain_term():
    offences: list[str] = []
    scanned = 0
    for directory in CLEAN_DIRECTORIES:
        for path in _files_in(directory):
            scanned += 1
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                hits = _scan(line)
                if hits:
                    offences.append(
                        f"{directory}/{path.name}:{lineno} names {sorted(hits)}: {line.strip()[:90]}"
                    )
    assert scanned, "scanned no files at all; this guard would pass vacuously"
    assert not offences, (
        "Law II violated -- domain meaning leaked out of backend/packs/:\n" + "\n".join(offences)
    )


def test_the_scanner_finds_those_terms_where_they_do_live(tmp_path):
    """Positive control, inline: proves the scanner is not silently broken.

    Run against text that definitely contains the terms. If this finds nothing, the clean
    result above means nothing either, and the build is wrong rather than merely imperfect.
    """
    fixture = tmp_path / "pack_like.yaml"
    fixture.write_text(
        "fields:\n"
        "  - name: annual_percentage_yield_pct\n"
        "    synonyms: ['APY', 'effective yield']\n"
        "  - name: minimum_deposit_usd\n"
        "    synonyms: ['Min. Deposit']\n"
        "institutions: [First National Bank, Pacific Savings, Metro Credit Union]\n"
        "products: [Money Market, High-Yield Savings, Checking Plus]\n",
        encoding="utf-8",
    )
    found = _scan(fixture.read_text(encoding="utf-8"))
    missing = {"apy", "bank", "money market", "pacific savings"} - found
    assert not missing, (
        f"the domain scanner failed to find {sorted(missing)} in material that contains "
        "them, so its clean verdict on the engine is worthless"
    )


def test_the_real_pack_directory_is_where_meaning_lives():
    """The other half of the control, against the actual pack once it exists."""
    pack_files = sorted(PACKS.glob("*.y*ml")) if PACKS.exists() else []
    if not pack_files:
        import pytest

        pytest.skip("no pack authored yet; the inline positive control above still runs")

    found: set[str] = set()
    for path in pack_files:
        found |= _scan(path.read_text(encoding="utf-8"))
    assert found, (
        f"the pack files {[p.name for p in pack_files]} contain none of the domain terms, "
        "which means either the pack is empty of meaning or the scanner is broken"
    )
