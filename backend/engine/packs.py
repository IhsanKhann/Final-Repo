"""Loads a customer's declarations out of YAML and refuses to let a bad one reach a run.

Why this module exists: meaning in this system lives in exactly one place, a pack file,
which is data the customer owns and can edit without touching code. This module is the
only door that data comes through, so it is also the only place where the shape of a
declaration is checked, and the only place where a claim can be stopped.

What it refuses to do:

- It refuses to know any vocabulary of its own. Every name, synonym, unit, factor and
  condition in a loaded pack comes out of the file; no word in this module is a word
  about anybody's subject matter. That is what lets a second pack in a different domain
  run on this same code with no edit at all (Law II), and it is why a reader will find no
  example values here.
- It refuses to let a malformed declaration be discovered late. A pack that does not load
  stops the whole run before the first document is opened, and the failure names the file
  and the LINE of the offending declaration, because "invalid pack" with no line is a
  scavenger hunt through someone else's YAML.
- It refuses a provenance tag without the fields that tag promises: a quotation with no
  document and page behind it, a judgement with no reasoning a reviewer can argue with,
  or a census with no count and no reproducible pattern (Law III). The three tags are not
  interchangeable and this loader will not let them blur into each other.
- It refuses to accept a declaration that calls itself accepted with no human attached.
  A drafted declaration is born PROPOSED; only a named person moves it.

Two checkers live here on purpose rather than in the test file: the one that opens a cited
document and looks for the quotation on the page named, and the one that re-runs a census
pattern over the data it claims to have counted. A guard that exists only in a test is a
guard the product does not actually own, and these two are the whole of Law III in
executable form.
"""

from __future__ import annotations

import csv
import re
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from backend.engine.contracts import (
    BusinessRule,
    SchemaField,
    SchemaPack,
    UnitConversion,
)

#: Written on a declaration whose `field` applies to every declared name rather than one.
ANY_FIELD = "*"

#: Page break inside a plain-text document, for the quotation checker.
_PAGE_BREAK = "\f"


# --- Failure ------------------------------------------------------------------


class PackError(Exception):
    """A pack cannot be used. Raised at load time, before any document is opened.

    The message always carries `file:line:` because that is the only form of this error a
    human can act on without a search.
    """

    def __init__(self, path: str | Path, line: int, message: str) -> None:
        self.path = str(path)
        self.line = int(line)
        self.message = message
        super().__init__(f"{self.path}:{self.line}: {message}")


# --- Provenance ---------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Quoted(_Strict):
    """The rule is written in the customer's own document. Nothing weaker counts."""

    tag: Literal["QUOTED"]
    doc_id: str = Field(min_length=1)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    note: str | None = None


class Authored(_Strict):
    """The customer's own judgement. `because` is mandatory so it can be argued with."""

    tag: Literal["AUTHORED"]
    because: str = Field(min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _reasoning_is_not_blank(self):
        if not self.because.strip():
            raise ValueError(
                "an AUTHORED declaration needs a `because` a reviewer can argue with, "
                "not whitespace"
            )
        return self


class Measured(_Strict):
    """A census over the customer's own data: the count, and how it was counted."""

    tag: Literal["MEASURED"]
    occurrences: int = Field(ge=0)
    pattern: str = Field(min_length=1)
    #: Defaults to the pack's own `measured_against` when not named here.
    dataset: str | None = None
    note: str | None = None


Provenance = Annotated[Union[Quoted, Authored, Measured], Field(discriminator="tag")]


# --- Declarations -------------------------------------------------------------


class Declaration(_Strict):
    """Common shape of every declaration, whatever group it sits in.

    `status` is the acceptance gate. A drafting agent may write PROPOSED and nothing else:
    moving one to ACCEPTED requires naming the human who did it.
    """

    status: Literal["PROPOSED", "ACCEPTED"] = "PROPOSED"
    accepted_by: str | None = None
    accepted_at: str | None = None
    provenance: Provenance

    #: Filled in by the loader after validation so any later failure can name the line.
    _line: int = PrivateAttr(default=0)
    _source_file: str = PrivateAttr(default="")

    @model_validator(mode="after")
    def _acceptance_needs_a_human(self):
        if self.status == "ACCEPTED" and not (self.accepted_by or "").strip():
            raise ValueError(
                "a declaration may not be ACCEPTED without `accepted_by` naming the "
                "person who accepted it; a drafted declaration stays PROPOSED"
            )
        return self

    @property
    def line(self) -> int:
        return self._line

    @property
    def source_file(self) -> str:
        return self._source_file


class Span(_Strict):
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _ordered(self):
        if self.min is not None and self.max is not None and self.max < self.min:
            raise ValueError(f"range max {self.max} is below min {self.min}")
        return self


class FieldDeclaration(Declaration):
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: Literal["number", "string", "date", "boolean"]
    unit: str | None = None
    required: bool = False
    synonyms: list[str] = Field(default_factory=list)
    #: A synonym that arrives in a unit other than this field's, so the lookup can tell
    #: the backbone which conversion to apply without anyone parsing the heading.
    synonym_units: dict[str, str] = Field(default_factory=dict)
    range: Span | None = None

    @property
    def key(self) -> str:
        return self.name


class ConversionDeclaration(Declaration):
    id: str = Field(min_length=1)
    from_unit: str = Field(min_length=1, alias="from")
    to_unit: str = Field(min_length=1, alias="to")
    factor: float
    #: For humans, and shown as written. The engine never composes this string.
    formula_text: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return self.id


class RuleDeclaration(Declaration):
    """Shared shape of the precedence, materiality and ambiguity groups.

    They differ in what they are about, not in what they look like, and the difference in
    what they are about is carried by the group they are declared in plus their
    provenance tag -- which is exactly where Law III wants it.
    """

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    #: None means the declaration applies to every declared name.
    field: str | None = None
    condition: str = Field(min_length=1)
    threshold: float | None = None
    action: Literal["flag", "reject", "warn"]
    description: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return self.id


# --- The pack -----------------------------------------------------------------


class Pack(_Strict):
    """A loaded, validated pack. Five declaration groups and nothing executable."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str | None = None
    status: Literal["PROPOSED", "ACCEPTED"] = "PROPOSED"
    #: Who accepted the pack as a whole, and when. Enforced exactly as it is per
    #: declaration, because this is the level where naming the human matters MOST: a pack
    #: accepted anonymously is the entire rulebook taking effect with nobody accountable
    #: for it, and "we did not write the customer's rules" stops being checkable.
    accepted_by: str | None = None
    accepted_at: str | None = None
    updated_at: str = Field(min_length=1)
    #: Repo-relative data file every MEASURED declaration is counted against by default.
    measured_against: str | None = None

    fields: list[FieldDeclaration] = Field(default_factory=list)
    conversions: list[ConversionDeclaration] = Field(default_factory=list)
    precedence: list[RuleDeclaration] = Field(default_factory=list)
    materiality: list[RuleDeclaration] = Field(default_factory=list)
    ambiguity: list[RuleDeclaration] = Field(default_factory=list)

    _source_file: str = PrivateAttr(default="")

    @model_validator(mode="after")
    def _acceptance_needs_a_human(self):
        """The same rule as per declaration, at the level where it matters most.

        Per-declaration acceptance was already enforced, but a pack as a whole could be
        marked ACCEPTED with nobody named -- so the rulebook could take effect without an
        accountable human, which is the one thing the provenance story exists to prevent.
        An agent promoting its own draft looks exactly like a legitimate acceptance except
        that nobody is named, so naming is the check.
        """
        if self.status == "ACCEPTED":
            if not (self.accepted_by or "").strip():
                raise ValueError(
                    "a pack may not be ACCEPTED without `accepted_by` naming the person "
                    "who accepted it; a drafted pack stays PROPOSED"
                )
            if not (self.accepted_at or "").strip():
                raise ValueError(
                    "a pack accepted without `accepted_at` cannot be audited: an "
                    "undated acceptance cannot be placed before or after the run it "
                    "governed"
                )
        return self

    @property
    def source_file(self) -> str:
        return self._source_file

    # -- the groups, addressed uniformly --------------------------------------

    @property
    def groups(self) -> dict[str, list[Declaration]]:
        return {
            "fields": list(self.fields),
            "conversions": list(self.conversions),
            "precedence": list(self.precedence),
            "materiality": list(self.materiality),
            "ambiguity": list(self.ambiguity),
        }

    @property
    def declarations(self) -> list[Declaration]:
        out: list[Declaration] = []
        for group in self.groups.values():
            out.extend(group)
        return out

    @property
    def rules(self) -> list[RuleDeclaration]:
        return [*self.precedence, *self.materiality, *self.ambiguity]

    # -- the lookups the mapper needs -----------------------------------------

    @cached_property
    def synonym_index(self) -> dict[str, str]:
        """Case-folded label -> declared name. Exact match only, deliberately.

        Fuzzy matching belongs upstream in retrieval, where it can be scored and shown.
        A lookup that silently almost-matches is how a value lands on the wrong name.
        """
        index: dict[str, str] = {}
        for declared in self.fields:
            for label in [declared.name, declared.label, *declared.synonyms]:
                index[label.casefold()] = declared.name
        return index

    @cached_property
    def unit_index(self) -> dict[str, str]:
        """Case-folded label -> the unit values arrive in under that label."""
        index: dict[str, str] = {}
        for declared in self.fields:
            for label in [declared.name, declared.label, *declared.synonyms]:
                if declared.unit is not None:
                    index[label.casefold()] = declared.unit
            for label, unit in declared.synonym_units.items():
                index[label.casefold()] = unit
        return index

    @cached_property
    def conversion_index(self) -> dict[tuple[str, str], ConversionDeclaration]:
        """(from_unit, to_unit) -> the declared conversion. The engine's whole table."""
        return {(c.from_unit, c.to_unit): c for c in self.conversions}

    @cached_property
    def field_index(self) -> dict[str, FieldDeclaration]:
        return {f.name: f for f in self.fields}

    def field_for_label(self, label: str) -> str | None:
        return self.synonym_index.get(label.casefold())

    def unit_for_label(self, label: str) -> str | None:
        return self.unit_index.get(label.casefold())

    def conversion_for(self, from_unit: str, to_unit: str) -> ConversionDeclaration | None:
        return self.conversion_index.get((from_unit, to_unit))


# --- Line numbers -------------------------------------------------------------


def _line_index(text: str, path: Path) -> dict[tuple[Any, ...], int]:
    """Path inside the document -> 1-based line, built from the composed node tree.

    safe_load throws the positions away, so the tree is walked once alongside it. Without
    this the loader can say a declaration is wrong but not where it is, which in a file
    of this size is barely better than silence.
    """
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:  # already reported by the caller, with its own mark
        raise _yaml_failure(exc, path) from exc

    index: dict[tuple[Any, ...], int] = {}

    def walk(node: Any, where: tuple[Any, ...]) -> None:
        index.setdefault(where, node.start_mark.line + 1)
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                child = where + (key_node.value,)
                # The key's own line, not the value's, which for a block mapping sits a
                # line below and reads as the wrong place to look.
                index[child] = key_node.start_mark.line + 1
                walk(value_node, child)
        elif isinstance(node, yaml.SequenceNode):
            for position, item in enumerate(node.value):
                walk(item, where + (position,))

    if root is not None:
        walk(root, ())
    return index


def _line_for(where: tuple[Any, ...], index: dict[tuple[Any, ...], int]) -> int:
    """Longest prefix of `where` that the document actually has a position for.

    A pydantic location can carry components the document never had -- the tag of a
    discriminated union, a name that is simply absent -- so the tail is trimmed until
    something real is left.
    """
    trimmed = tuple(where)
    while trimmed:
        if trimmed in index:
            return index[trimmed]
        trimmed = trimmed[:-1]
    return index.get((), 1)


def _yaml_failure(exc: yaml.YAMLError, path: Path) -> PackError:
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    line = (mark.line + 1) if mark is not None else 1
    problem = getattr(exc, "problem", None) or str(exc)
    return PackError(path, line, f"the file is not valid YAML: {problem}")


# --- Loading ------------------------------------------------------------------


def default_pack_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "packs"


def load_pack(path: str | Path) -> Pack:
    """Read one pack, or raise PackError naming the file and the line. No partial loads.

    Called at start-up: a run with a bad pack must not reach its first document, because
    every value that run would produce would be governed by declarations nobody validated.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackError(path, 1, f"cannot be read: {exc.strerror or exc}") from exc

    index = _line_index(text, path)

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise _yaml_failure(exc, path) from exc

    if not isinstance(raw, dict):
        raise PackError(path, 1, "a pack must be a mapping of declaration groups")

    try:
        pack = Pack.model_validate(raw)
    except ValidationError as exc:
        raise _from_validation_error(exc, path, index) from exc

    pack._source_file = str(path)
    _attach_lines(pack, path, index)
    _cross_check(pack, path)
    return pack


def load_packs(directory: str | Path | None = None) -> dict[str, Pack]:
    """Every pack in a directory, keyed by id. One bad file fails the lot, by design."""
    directory = Path(directory) if directory is not None else default_pack_dir()
    found: dict[str, Pack] = {}
    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        pack = load_pack(path)
        if pack.id in found:
            raise PackError(path, 1, f"a second pack claims the id {pack.id!r}")
        found[pack.id] = pack
    return found


def resolve_active_pack(
    active_pack_id: str | None, directory: str | Path | None = None
) -> Pack:
    """Pick the pack a run uses, or block the run rather than guessing.

    `active_pack_id` is empty by default because a pack id is a domain noun and Law II
    keeps those out of engine code -- a pack id stored in the config database is data and
    fine, but one written into a module is meaning in the wrong place.

    So an unset value means "the single pack in packs/". If there is more than one and
    nothing is stored, the run is BLOCKED and names the packs it found. It never silently
    picks the first: that would make a run's governing rulebook depend on filename order,
    and the whole product rests on knowing which rulebook decided a value.
    """
    directory = Path(directory) if directory is not None else default_pack_dir()
    available = load_packs(directory)

    if not available:
        raise PackError(directory / "<none>", 1, "no pack found; a run needs a rulebook")

    wanted = (active_pack_id or "").strip()
    if wanted:
        if wanted not in available:
            raise PackError(
                directory / "<none>",
                1,
                f"the configured active pack {wanted!r} is not here; found "
                f"{sorted(available)}",
            )
        return available[wanted]

    if len(available) > 1:
        raise PackError(
            directory / "<none>",
            1,
            f"{len(available)} packs are present ({sorted(available)}) and no active pack "
            "is configured. Set one in the config store rather than letting the run guess "
            "which rulebook governs.",
        )

    return next(iter(available.values()))


def _from_validation_error(
    exc: ValidationError, path: Path, index: dict[tuple[Any, ...], int]
) -> PackError:
    first = exc.errors()[0]
    where = tuple(first.get("loc", ()))
    if first.get("type") in ("union_tag_invalid", "union_tag_not_found"):
        # A bad provenance tag is reported against the block; the offending word is on
        # the tag's own line, which is where a reader needs to be sent.
        where = where + ("tag",)
    line = _line_for(where, index)
    readable = ".".join(str(part) for part in where) or "<the pack itself>"
    return PackError(path, line, f"{readable}: {first.get('msg', 'is invalid')}")


def _attach_lines(pack: Pack, path: Path, index: dict[tuple[Any, ...], int]) -> None:
    for group_name, group in pack.groups.items():
        for position, declaration in enumerate(group):
            declaration._line = _line_for((group_name, position), index)
            declaration._source_file = str(path)


def _cross_check(pack: Pack, path: Path) -> None:
    """Checks that need the whole file in view, each reported at its own line."""
    seen_names: dict[str, FieldDeclaration] = {}
    claimed: dict[str, str] = {}

    for declared in pack.fields:
        if declared.name in seen_names:
            raise PackError(path, declared.line, f"the name {declared.name!r} is declared twice")
        seen_names[declared.name] = declared

        for label in [declared.name, declared.label, *declared.synonyms]:
            folded = label.casefold()
            owner = claimed.get(folded)
            if owner is not None and owner != declared.name:
                raise PackError(
                    path,
                    declared.line,
                    f"the label {label!r} is claimed by both {owner!r} and "
                    f"{declared.name!r}; one label cannot resolve to two names",
                )
            claimed[folded] = declared.name

        known = {lbl.casefold() for lbl in [declared.name, declared.label, *declared.synonyms]}
        for label, unit in declared.synonym_units.items():
            if label.casefold() not in known:
                raise PackError(
                    path,
                    declared.line,
                    f"synonym_units names {label!r}, which is not a synonym of "
                    f"{declared.name!r}",
                )
            if unit != declared.unit and (unit, declared.unit) not in {
                (c.from_unit, c.to_unit) for c in pack.conversions
            }:
                raise PackError(
                    path,
                    declared.line,
                    f"{label!r} arrives as {unit!r} but no conversion to "
                    f"{declared.unit!r} is declared",
                )

    seen_ids: set[str] = set()
    pairs: dict[tuple[str, str], str] = {}
    for conversion in pack.conversions:
        if conversion.id in seen_ids:
            raise PackError(
                path, conversion.line, f"the id {conversion.id!r} is declared twice"
            )
        seen_ids.add(conversion.id)
        pair = (conversion.from_unit, conversion.to_unit)
        if pair in pairs:
            raise PackError(
                path,
                conversion.line,
                f"{pair[0]!r} -> {pair[1]!r} is declared twice, by {pairs[pair]!r} too; "
                "a conversion table cannot hold two factors for one pair",
            )
        pairs[pair] = conversion.id

    for rule in pack.rules:
        if rule.id in seen_ids:
            raise PackError(path, rule.line, f"the id {rule.id!r} is declared twice")
        seen_ids.add(rule.id)
        if rule.field not in (None, ANY_FIELD) and rule.field not in seen_names:
            raise PackError(
                path,
                rule.line,
                f"{rule.id!r} is about {rule.field!r}, which this pack does not declare",
            )


# --- The shape the schema screen consumes -------------------------------------


def to_schema_pack(pack: Pack) -> SchemaPack:
    """Project a pack onto the frontend's own type. A projection, never a second source.

    Note what is dropped: provenance, acceptance status and the reasoning behind every
    judgement. The frontend type has nowhere to put them, and inventing a place for them
    here would mean two definitions of a pack. They stay queryable on the Pack itself.
    """
    return SchemaPack(
        id=pack.id,
        name=pack.name,
        version=pack.version,
        description=pack.description,
        fields=[
            SchemaField(
                name=f.name,
                label=f.label,
                type=f.type,
                unit=f.unit,
                required=f.required,
                synonyms=list(f.synonyms),
            )
            for f in pack.fields
        ],
        conversions=[
            UnitConversion(
                id=c.id,
                from_unit=c.from_unit,
                to_unit=c.to_unit,
                factor=c.factor,
                formula=c.formula_text,
            )
            for c in pack.conversions
        ],
        rules=[
            BusinessRule(
                id=r.id,
                name=r.name,
                field=r.field or ANY_FIELD,
                condition=r.condition,
                action=r.action,
                description=r.description,
            )
            for r in pack.rules
        ],
        updated_at=pack.updated_at,
    )


# --- Law III, executable ------------------------------------------------------


class QuoteCheck(BaseModel):
    """Whether a quotation is really in the document it cites, on the page it names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    detail: str


def _squash(text: str) -> str:
    """Whitespace-insensitive comparison, because line wrapping is not a difference."""
    return " ".join(text.split())


def _pages_of(path: Path) -> list[str] | None:
    if path.suffix.casefold() == ".pdf":
        try:
            import pdfplumber  # imported here so a pack with no PDF needs no library
        except ImportError:
            return None
        with pdfplumber.open(str(path)) as opened:
            return [(page.extract_text() or "") for page in opened.pages]
    return path.read_text(encoding="utf-8", errors="replace").split(_PAGE_BREAK)


def check_quote(provenance: Quoted, root: str | Path) -> QuoteCheck:
    """Open the cited document and look for the quotation on the page it names.

    `root` is what doc_id is relative to. Anything other than a found, matching quotation
    is a failure, including a document that cannot be opened: a citation nobody can check
    is not a citation.
    """
    cited = Path(root) / provenance.doc_id
    if not cited.is_file():
        return QuoteCheck(ok=False, detail=f"no such document: {cited}")

    pages = _pages_of(cited)
    if pages is None:
        return QuoteCheck(
            ok=False, detail=f"{cited} cannot be opened: no library for its format"
        )
    if provenance.page > len(pages):
        return QuoteCheck(
            ok=False,
            detail=f"{cited} has {len(pages)} page(s); the citation names page "
            f"{provenance.page}",
        )

    wanted = _squash(provenance.quote)
    if wanted in _squash(pages[provenance.page - 1]):
        return QuoteCheck(ok=True, detail=f"found on page {provenance.page} of {cited}")

    elsewhere = [
        number
        for number, body in enumerate(pages, start=1)
        if wanted in _squash(body)
    ]
    if elsewhere:
        return QuoteCheck(
            ok=False,
            detail=f"the quotation is in {cited} but on page(s) {elsewhere}, not page "
            f"{provenance.page}",
        )
    return QuoteCheck(ok=False, detail=f"the quotation does not appear in {cited}")


_TALLY_ALL = re.compile(r"^count\(\s*rows\s*\)$", re.IGNORECASE)
_TALLY_DISTINCT = re.compile(r"^count\(\s*distinct\s+([A-Za-z_][A-Za-z0-9_]*)\s*\)$", re.IGNORECASE)
_TALLY_WHERE = re.compile(
    r"^count\(\s*rows\s+where\s+([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*\)$",
    re.IGNORECASE,
)


def _as_number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compare(left: str, operator: str, right: str) -> bool:
    lhs: Any = _as_number(left)
    rhs: Any = _as_number(right)
    if lhs is None or rhs is None:
        lhs, rhs = left.strip().casefold(), right.strip().casefold()
        if operator not in ("==", "!="):
            raise ValueError(f"{operator!r} cannot order {left!r} against {right!r}")
    return {
        "==": lhs == rhs,
        "!=": lhs != rhs,
        ">=": lhs >= rhs,
        "<=": lhs <= rhs,
        ">": lhs > rhs,
        "<": lhs < rhs,
    }[operator]


def _run_pattern(pattern: str, rows: list[dict[str, str]], columns: list[str]) -> int:
    """The census patterns a MEASURED declaration is allowed to claim.

    Deliberately four forms and no expression evaluator: a pattern is a claim a reviewer
    has to be able to read, and anything a reviewer cannot read is not a justification.
    """
    pattern = pattern.strip()

    if _TALLY_ALL.match(pattern):
        return len(rows)

    distinct = _TALLY_DISTINCT.match(pattern)
    if distinct:
        column = distinct.group(1)
        if column not in columns:
            raise ValueError(f"the data has no column {column!r}")
        return len({row[column] for row in rows})

    where = _TALLY_WHERE.match(pattern)
    if where:
        column, operator, against = where.group(1), where.group(2), where.group(3).strip()
        if column not in columns:
            raise ValueError(f"the data has no column {column!r}")
        other = against if against in columns else None
        literal = against.strip("'\"")
        total = 0
        for row in rows:
            right = row[other] if other is not None else literal
            if _compare(row[column], operator, right):
                total += 1
        return total

    raise ValueError(
        f"{pattern!r} is not a census pattern this loader can re-run; use count(rows), "
        "count(distinct <column>) or count(rows where <column> <op> <value|column>)"
    )


def recount(pack: Pack, declaration: Declaration, root: str | Path) -> int:
    """Re-run a MEASURED declaration's pattern over the data and return the real count.

    This is the whole weight behind a MEASURED tag: a number nobody can reproduce is an
    assertion wearing a census's clothes. CI runs this on every declaration, so a claim
    that stops being true stops the pack from shipping.
    """
    provenance = declaration.provenance
    if not isinstance(provenance, Measured):
        raise PackError(
            declaration.source_file or str(root),
            declaration.line,
            "only a MEASURED declaration has a count to reproduce",
        )

    named = provenance.dataset or pack.measured_against
    if not named:
        raise PackError(
            declaration.source_file or str(root),
            declaration.line,
            "names no data to have been counted against, and the pack declares no "
            "`measured_against` either",
        )

    data = Path(root) / named
    if not data.is_file():
        raise PackError(
            declaration.source_file or str(root),
            declaration.line,
            f"counts against {data}, which does not exist",
        )

    with data.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)

    try:
        return _run_pattern(provenance.pattern, rows, columns)
    except ValueError as exc:
        raise PackError(
            declaration.source_file or str(root), declaration.line, str(exc)
        ) from exc


__all__ = [
    "ANY_FIELD",
    "PackError",
    "Quoted",
    "Authored",
    "Measured",
    "Provenance",
    "Declaration",
    "Span",
    "FieldDeclaration",
    "ConversionDeclaration",
    "RuleDeclaration",
    "Pack",
    "QuoteCheck",
    "default_pack_dir",
    "load_pack",
    "load_packs",
    "resolve_active_pack",
    "to_schema_pack",
    "check_quote",
    "recount",
]
