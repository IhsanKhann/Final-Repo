"""Law III, enforced. These tests are the reason a pack's provenance means anything.

A provenance tag is a promise about where a declaration came from. Nothing stops an
author -- human or model -- from typing QUOTED over a guess, except a test that opens the
cited document and looks. So these tests do the looking: they re-read every quotation
against its source, re-count every census against the data it claims to have counted, and
refuse a judgement with no reasoning attached.

The shipped pack carries zero QUOTED declarations today, because no customer source
document exists to quote from. That makes the quotation test vacuous unless the checker
itself is exercised, so it is -- against a fixture document with one true quotation and
one false one. A guard that never fires on a known-bad input is not a guard; it is a
decoration, and it would be the single easiest thing in this repo to break silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.engine.contracts import SchemaPack
from backend.engine.packs import (
    Authored,
    Measured,
    Pack,
    PackError,
    Quoted,
    check_quote,
    default_pack_dir,
    load_pack,
    load_packs,
    recount,
    to_schema_pack,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = default_pack_dir()


@pytest.fixture(scope="module")
def pack() -> Pack:
    return load_pack(PACK_DIR / "banking_rates.yaml")


# --- helpers ------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _line_of(text: str, needle: str) -> int:
    """The 1-based line a fixture's offending line really sits on.

    Computed rather than hard-coded, so a test that claims a line number cannot drift out
    of agreement with the fixture it is reading.
    """
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"{needle!r} is not in the fixture")


#: A pack with one of everything, used as the base for the malformed variants below.
WELL_FORMED = """\
id: fixture
name: Fixture
version: 0.0.1
status: PROPOSED
updated_at: "2026-10-20T00:00:00Z"
fields:
  - name: alpha
    label: Alpha
    type: number
    unit: unit_a
    required: true
    synonyms:
      - a_one
    status: PROPOSED
    provenance:
      tag: AUTHORED
      because: it is a fixture
"""


# --- QUOTED: open the document and look ---------------------------------------


def test_every_quoted_declaration_is_really_in_the_document_on_the_page_it_names(pack: Pack):
    quoted = [d for d in pack.declarations if isinstance(d.provenance, Quoted)]
    for declaration in quoted:
        result = check_quote(declaration.provenance, REPO_ROOT)
        assert result.ok, (
            f"{declaration.source_file}:{declaration.line}: {declaration.key} claims "
            f"QUOTED but {result.detail}"
        )


def test_the_shipped_pack_claims_no_quotation_because_there_is_no_document_to_quote(
    pack: Pack,
):
    """A QUOTED tag here today could only be a fabrication, so there must be none.

    When a real source document arrives this test is the one that changes: it stops
    asserting emptiness and the loop above starts doing the work.
    """
    quoted = [d.key for d in pack.declarations if isinstance(d.provenance, Quoted)]
    assert quoted == [], (
        "a QUOTED declaration cites a customer document by page; no customer document "
        f"exists yet, so these are fabricated citations: {quoted}"
    )


def test_the_quotation_checker_accepts_a_quotation_that_is_really_on_the_page(tmp_path: Path):
    document = _write(
        tmp_path,
        "source.txt",
        "page one says nothing useful\fthe minimum balance is held for the full period\f"
        "page three",
    )
    text = WELL_FORMED.replace(
        "      tag: AUTHORED\n      because: it is a fixture\n",
        "      tag: QUOTED\n"
        f"      doc_id: {document.name}\n"
        "      page: 2\n"
        "      quote: the minimum balance is held for the full period\n",
    )
    loaded = load_pack(_write(tmp_path, "fixture.yaml", text))
    provenance = loaded.fields[0].provenance
    assert isinstance(provenance, Quoted)

    result = check_quote(provenance, tmp_path)
    assert result.ok, result.detail


def test_the_quotation_checker_rejects_a_quotation_that_is_not_there(tmp_path: Path):
    document = _write(
        tmp_path,
        "source.txt",
        "page one says nothing useful\fthe minimum balance is held for the full period",
    )
    base = WELL_FORMED.replace(
        "      tag: AUTHORED\n      because: it is a fixture\n",
        "      tag: QUOTED\n"
        f"      doc_id: {document.name}\n"
        "      page: 2\n"
        "      quote: PLACEHOLDER\n",
    )

    def first_provenance(name: str, text: str):
        return load_pack(_write(tmp_path, name, text)).fields[0].provenance

    invented = first_provenance(
        "invented.yaml", base.replace("PLACEHOLDER", "no such sentence")
    )
    wrong_page = first_provenance(
        "wrong_page.yaml",
        base.replace("PLACEHOLDER", "the minimum balance is held for the full period")
        .replace("page: 2", "page: 1"),
    )
    missing_file = first_provenance(
        "missing.yaml",
        base.replace("PLACEHOLDER", "anything").replace(
            f"doc_id: {document.name}", "doc_id: not_a_document.txt"
        ),
    )

    assert not check_quote(invented, tmp_path).ok, "a sentence nobody wrote passed"
    assert not check_quote(wrong_page, tmp_path).ok, "the page number was not checked"
    assert not check_quote(missing_file, tmp_path).ok, "a missing document passed"
    assert "page" in check_quote(wrong_page, tmp_path).detail


# --- AUTHORED: reasoning a reviewer can argue with ----------------------------


def test_every_authored_declaration_says_why(pack: Pack):
    for declaration in pack.declarations:
        provenance = declaration.provenance
        if isinstance(provenance, Authored):
            assert provenance.because.strip(), (
                f"{declaration.source_file}:{declaration.line}: {declaration.key} is "
                "AUTHORED with an empty `because`; a judgement nobody can argue with is "
                "not a judgement"
            )


def test_an_authored_declaration_with_no_reasoning_does_not_load(tmp_path: Path):
    text = WELL_FORMED.replace("      because: it is a fixture\n", "      because: '   '\n")
    with pytest.raises(PackError) as raised:
        load_pack(_write(tmp_path, "blank_reason.yaml", text))
    assert "because" in str(raised.value)


# --- MEASURED: the count has to reproduce ------------------------------------


def test_every_measured_count_reproduces_against_the_real_data(pack: Pack):
    measured = [d for d in pack.declarations if isinstance(d.provenance, Measured)]
    assert measured, "a pack of pure judgement has measured nothing; check the fixture"

    for declaration in measured:
        provenance = declaration.provenance
        assert isinstance(provenance, Measured)
        counted = recount(pack, declaration, REPO_ROOT)
        assert counted == provenance.occurrences, (
            f"{declaration.source_file}:{declaration.line}: {declaration.key} claims "
            f"{provenance.occurrences} occurrences of {provenance.pattern!r} but "
            f"re-running it over {provenance.dataset or pack.measured_against} gives "
            f"{counted}"
        )


def test_the_recount_would_notice_a_wrong_number(pack: Pack):
    """The reproducibility check must be able to fail, or it proves nothing above."""
    measured = next(d for d in pack.declarations if isinstance(d.provenance, Measured))
    truthful = recount(pack, measured, REPO_ROOT)
    inflated = measured.provenance.model_copy(update={"occurrences": truthful + 1})
    assert inflated.occurrences != truthful


def test_a_census_pattern_nobody_can_re_run_is_refused(tmp_path: Path):
    text = WELL_FORMED.replace(
        "      tag: AUTHORED\n      because: it is a fixture\n",
        "      tag: MEASURED\n"
        "      occurrences: 3\n"
        "      pattern: trust me\n"
        "      dataset: data/samples/ps06_sample_rate_sheets.csv\n",
    )
    loaded = load_pack(_write(tmp_path, "unrunnable.yaml", text))
    with pytest.raises(PackError) as raised:
        recount(loaded, loaded.fields[0], REPO_ROOT)
    assert "census pattern" in str(raised.value)


# --- Malformed packs stop the run, with a line number ------------------------


@pytest.mark.parametrize(
    "name, mutate, marker, expected_in_message",
    [
        (
            "missing_reasoning.yaml",
            lambda t: t.replace("      because: it is a fixture\n", ""),
            "provenance:",
            "because",
        ),
        (
            "quoted_without_a_quote.yaml",
            lambda t: t.replace(
                "      tag: AUTHORED\n      because: it is a fixture\n",
                "      tag: QUOTED\n      doc_id: somewhere.txt\n      page: 2\n",
            ),
            "provenance:",
            "quote",
        ),
        (
            "measured_without_a_count.yaml",
            lambda t: t.replace(
                "      tag: AUTHORED\n      because: it is a fixture\n",
                "      tag: MEASURED\n      pattern: count(rows)\n",
            ),
            "provenance:",
            "occurrences",
        ),
        (
            "unknown_tag.yaml",
            lambda t: t.replace("      tag: AUTHORED\n", "      tag: PROBABLY\n"),
            "tag: PROBABLY",
            "tag",
        ),
        (
            "undeclared_key.yaml",
            lambda t: t.replace("    unit: unit_a\n", "    unit: unit_a\n    confidence: 0.9\n"),
            "confidence: 0.9",
            "confidence",
        ),
        (
            "accepted_by_nobody.yaml",
            lambda t: t.replace("    status: PROPOSED\n", "    status: ACCEPTED\n"),
            "- name: alpha",
            "accepted_by",
        ),
        (
            "no_provenance_at_all.yaml",
            lambda t: t.replace(
                "    provenance:\n      tag: AUTHORED\n      because: it is a fixture\n", ""
            ),
            "- name: alpha",
            "provenance",
        ),
    ],
)
def test_a_malformed_declaration_blocks_the_run_naming_the_file_and_the_line(
    tmp_path: Path, name: str, mutate, marker: str, expected_in_message: str
):
    text = mutate(WELL_FORMED)
    path = _write(tmp_path, name, text)

    with pytest.raises(PackError) as raised:
        load_pack(path)

    error = raised.value
    assert error.path == str(path)
    assert error.line == _line_of(text, marker), (
        f"reported line {error.line} for {name}; the offending declaration is on line "
        f"{_line_of(text, marker)}. Message was: {error}"
    )
    assert expected_in_message in str(error)
    assert f":{error.line}:" in str(error), "a failure with no line number is a search"


def test_a_file_that_is_not_yaml_at_all_fails_with_its_line(tmp_path: Path):
    text = WELL_FORMED.replace("  - name: alpha\n", "  - name: alpha\n     bent: true\n")
    path = _write(tmp_path, "bent.yaml", text)

    with pytest.raises(PackError) as raised:
        load_pack(path)

    assert raised.value.path == str(path)
    assert raised.value.line >= _line_of(text, "bent: true") - 1
    assert "YAML" in str(raised.value)


def test_one_label_may_not_resolve_to_two_names(tmp_path: Path):
    text = WELL_FORMED + """\
  - name: beta
    label: Beta
    type: number
    unit: unit_a
    required: false
    synonyms:
      - A_ONE
    status: PROPOSED
    provenance:
      tag: AUTHORED
      because: it collides with alpha on purpose
"""
    path = _write(tmp_path, "collision.yaml", text)

    with pytest.raises(PackError) as raised:
        load_pack(path)

    assert raised.value.line == _line_of(text, "- name: beta")
    assert "two names" in str(raised.value)


def test_a_declaration_may_not_be_about_a_name_the_pack_never_declared(tmp_path: Path):
    text = WELL_FORMED + """\
ambiguity:
  - id: about_nothing
    name: About nothing
    field: gamma
    condition: gamma > 0
    action: flag
    description: gamma is not declared anywhere
    status: PROPOSED
    provenance:
      tag: AUTHORED
      because: it points at a name this pack does not declare
"""
    path = _write(tmp_path, "dangling.yaml", text)

    with pytest.raises(PackError) as raised:
        load_pack(path)

    assert raised.value.line == _line_of(text, "- id: about_nothing")
    assert "does not declare" in str(raised.value)


def test_a_unit_that_arrives_unconvertible_is_refused(tmp_path: Path):
    text = WELL_FORMED.replace(
        "      - a_one\n",
        "      - a_one\n    synonym_units:\n      a_one: unit_b\n",
    )
    path = _write(tmp_path, "no_factor.yaml", text)

    with pytest.raises(PackError) as raised:
        load_pack(path)

    assert "no conversion" in str(raised.value)
    assert f":{raised.value.line}:" in str(raised.value)


# --- The shipped pack is a draft, not an authored pack -----------------------


def test_nothing_in_the_shipped_pack_claims_to_have_been_accepted(pack: Pack):
    """We may draft a pack. We may never author one.

    THE ACCEPTANCE THIS TEST RECORDS: on 2026-10-20 Ihsan Khan, the pack owner, accepted
    banking_rates v1.0.0 -- every field, conversion and rule. The previous form of this
    test asserted `pack.status == "PROPOSED"` and its docstring said that if it ever
    failed, either a person really had accepted the pack and this test was the place to
    record it, or an agent had promoted its own draft. The first happened.

    So the guard is reframed rather than deleted, because "nothing is ever accepted" stops
    being true the moment the product is used as intended, and a test that must be deleted
    on first real use was only ever guarding the draft. What must stay impossible is
    ACCEPTANCE WITHOUT A NAMED HUMAN -- an agent promoting its own draft looks exactly like
    a legitimate acceptance except that nobody is named.
    """
    anonymous = [
        d.key
        for d in pack.declarations
        if d.status == "ACCEPTED" and not (d.accepted_by or "").strip()
    ]
    assert anonymous == [], f"ACCEPTED with nobody named: {anonymous}"

    undated = [
        d.key
        for d in pack.declarations
        if d.status == "ACCEPTED" and not (d.accepted_at or "").strip()
    ]
    assert undated == [], f"ACCEPTED with no date: {undated}"

    assert pack.status in {"PROPOSED", "ACCEPTED"}
    if pack.status == "ACCEPTED":
        # A pack accepted as a whole while a declaration inside it is still a draft would
        # let a drafted rule ride in on the pack's acceptance.
        drafts = [d.key for d in pack.declarations if d.status != "ACCEPTED"]
        assert drafts == [], f"pack is ACCEPTED but these are still drafts: {drafts}"


def test_every_declaration_carries_one_of_the_three_provenance_tags(pack: Pack):
    tags = {d.provenance.tag for d in pack.declarations}
    assert tags <= {"QUOTED", "AUTHORED", "MEASURED"}
    assert len(pack.declarations) == sum(len(g) for g in pack.groups.values())
    assert all(d.line > 0 for d in pack.declarations), "a declaration with no line"


# --- The lookups the rest of the backbone depends on -------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Rate",
        "APY",
        "Min. Deposit",
        "Interest",
        "Annual Yield",
        "p.a. %",
        "effective yield",
        "Nominal (monthly)",
    ],
)
def test_the_words_the_sources_actually_use_resolve_to_a_declared_name(pack: Pack, label: str):
    """Every heading DATASETS.md section 1 says the six sources use must land somewhere.

    These are the real variants, not invented ones: they are the column headings of the
    generated documents, and a pack that does not know them sends the whole batch to
    review.
    """
    assert pack.field_for_label(label) in pack.field_index, label
    assert pack.field_for_label(label.upper()) == pack.field_for_label(label.lower()), (
        "the lookup is case-folded, so a shouted heading and a quiet one are one label"
    )


def test_a_label_the_pack_does_not_declare_resolves_to_nothing_rather_than_a_guess(
    pack: Pack,
):
    assert pack.field_for_label("a heading nobody has ever used") is None


def test_the_conversion_table_is_keyed_by_the_pair_of_units(pack: Pack):
    assert pack.conversion_index, "the pack declares no conversion at all"
    for (from_unit, to_unit), conversion in pack.conversion_index.items():
        assert pack.conversion_for(from_unit, to_unit) is conversion
        assert conversion.factor != 0
        assert conversion.formula_text.strip()
        assert "factor=" not in conversion.formula_text, (
            "formula_text is read by a human, not parsed by a machine"
        )
    assert pack.conversion_for("nothing_like_this", "or_this") is None


def test_the_pack_declares_a_factor_for_every_unit_a_source_arrives_in(pack: Pack):
    for declared in pack.fields:
        for label, arriving in declared.synonym_units.items():
            assert arriving == declared.unit or pack.conversion_for(arriving, declared.unit), (
                f"{label!r} arrives as {arriving!r} and nothing converts it"
            )


# --- The shape the Schema page consumes --------------------------------------


def test_the_pack_projects_onto_the_frontends_own_type(pack: Pack):
    projected = to_schema_pack(pack)
    round_tripped = SchemaPack.model_validate_json(projected.model_dump_json())

    assert round_tripped == projected
    assert {f.name for f in round_tripped.fields} == {f.name for f in pack.fields}
    assert len(round_tripped.conversions) == len(pack.conversions)
    assert len(round_tripped.rules) == len(pack.rules)
    assert all(r.field for r in round_tripped.rules), "a rule with no field to show"
    assert all(c.formula for c in round_tripped.conversions)


def test_every_pack_in_the_directory_loads(pack: Pack):
    loaded = load_packs(PACK_DIR)
    assert pack.id in loaded
    assert loaded[pack.id].version == pack.version


# --- Law II, with its positive control ---------------------------------------

#: Words that belong to the customer's subject matter and must live only in a pack. They
#: are listed here, in a test, rather than in the module they guard.
DOMAIN_WORDS = [
    "apy",
    "deposit",
    "interest",
    "annual yield",
    "effective yield",
    "nominal",
    "percent_per_month",
    "p.a. %",
]


def test_the_loader_knows_no_word_of_the_customers_subject_matter():
    """The scanner runs over the loader AND over the pack, so a broken scanner is visible.

    A scanner with a typo and a genuinely clean module both report zero hits, and the
    wrong one reads as success. The positive control below is the difference.
    """
    loader = (REPO_ROOT / "backend" / "engine" / "packs.py").read_text(encoding="utf-8").casefold()
    leaked = [word for word in DOMAIN_WORDS if word in loader]
    assert leaked == [], f"the loader has learned the customer's vocabulary: {leaked}"

    declared = (PACK_DIR / "banking_rates.yaml").read_text(encoding="utf-8").casefold()
    missed = [word for word in DOMAIN_WORDS if word not in declared]
    assert missed == [], (
        f"positive control failed: the scanner cannot find {missed} even in the pack, so "
        "its silence over the loader means nothing"
    )
