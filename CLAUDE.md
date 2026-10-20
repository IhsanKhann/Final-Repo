# CLAUDE.md — rules for AI coding agents on this repo

You are writing code for **PS-12, Cross-Source Data Standardization & Transformation
Agent**, National AI Hackathon '26. Read [`README.md`](README.md) first — it is the
standard and it carries the problem statement verbatim. This file is what you must not
get wrong.

**Time budget is hours, not days.** Prefer the smallest thing that is correct, complete
and demonstrable. Do not add abstraction nobody asked for. Do not refactor another lane's
code.

---

## 0. The one-paragraph brief

Documents arrive from unlike sources in unlike formats. We extract reportable fields,
map each one onto a field the **customer** declared in a YAML domain pack, convert its
units using factors the **customer** declared, flag anything we are not sure about for a
human instead of guessing, and learn from every correction so the next run is measurably
better. Every value in the output carries the page it came from.

---

## 1. Five laws. Break one and the build is wrong, not just imperfect.

### Law I — the backbone is deterministic
**No model call may appear anywhere under `backend/engine/`.** Not a client, not an
import, not "just for the edge case". The engine takes proposals in as plain data and
returns decisions. Same input, same version → same output, bit for bit.
Guard: `tests/test_no_model_call_in_engine.py` greps for provider imports and client
constructions under `engine/`.

### Law II — meaning lives only in the pack
**No domain proper noun may appear outside `backend/packs/`.** No `APY`, no
`money_market`, no bank name, no `rate_sheet` literal in `engine/`, `adapters/`, `api/`
or the frontend. Those words belong in a pack YAML, which is data.
Guard: `tests/test_engine_is_domain_agnostic.py`, which scans the engine for a term list
**and has a positive control** — the same scanner over `packs/` must find those terms. A
scanner broken by a typo and a genuinely clean engine both return zero, and the wrong one
reads as success.

### Law III — nothing is invented
Every declaration in a pack carries its own provenance, and the three values are not
interchangeable:

| tag | means | mandatory fields |
|---|---|---|
| `QUOTED` | the rule is in the customer's source document | `doc_id`, `page`, verbatim `quote` |
| `AUTHORED` | the customer's own judgement | `because` — so a reviewer can argue with the reasoning |
| `MEASURED` | a census over the customer's own data | `occurrences` and the `pattern` that produced it |

The asymmetry is the point. An `AUTHORED` precedence rule would be *us* deciding which of
someone's instruments governs — the one thing this product exists to refuse.
Guard: `tests/test_packs.py` opens every file a pack cites and checks the quote is really
there, on the page the pack names.

**You may draft a pack. You may never author one.** A drafted declaration is born
`PROPOSED` and takes effect only when a human accepts it.

### Law IV — the export is a render, not a generation
No model call in the export path. Same data in → byte-identical file out.
Guard: `tests/test_render_is_byte_identical.py`.

### Law V — three states, never two
`auto` / `review` / `missing`. Never a boolean. The interesting case is always the middle
one.

---

## 2. The contract is `Frontend/src/api/types.ts`

It was written first. **The backend conforms to it. Do not edit it to match your code.**

```
MappingStatus   'auto' | 'review' | 'missing' | 'approved' | 'rejected'
BatchStage      'uploading'|'ingesting'|'parsing'|'mapping'|'normalizing'|'validating'|'ready'|'failed'
SourceLocation  {type:'pdf', page, bbox:[x,y,w,h]}        bbox NORMALIZED 0–1
                {type:'sheet', sheet, cell}               e.g. "B12"
                {type:'text', start, end}                 character offsets
Conversion      {factor, rule_id, formula_text}
Mapping         {id, document_id, source_label, target_field, raw_value, raw_unit?,
                 value, unit?, confidence, status, reason?, conversion?,
                 validations[], source_location}
```

Hard rules that follow from it:
- The third lane is **`missing`**, never "refused" or "rejected_low_confidence". Use the
  word `missing` in Python too.
- bbox is **normalized 0–1 `[x, y, w, h]`**. Adapters convert on the way out. A PDF
  library that gives you absolute points must be divided by page width/height, once,
  in the adapter — never in the UI.
- `confidence` is a float 0–1, never a percentage.
- `formula_text` is for humans: `"× 12 (monthly → annual)"`, not `"factor=12"`.

Endpoints are listed in `Frontend/src/api/endpoints.ts`. Implement exactly those paths.
`mockData.ts` shows the exact shapes the UI expects — treat it as the fixture.

---

## 3. What each PS-12 requirement means in code

| Requirement | Where it lives | What "done" means |
|---|---|---|
| **Multi-format ingestion** | `adapters/` — one module per format, no shared state | CSV, XLSX, HTML, text PDF, scanned PDF each produce `ExtractedFact[]` with a `source_location`. A corrupt file marks *that document* unreadable and the batch continues. |
| **Intelligent field mapping** | `intelligence/mapper.py` proposes, `engine/resolve.py` decides | Candidates retrieved deterministically from pack synonyms + tenant precedents; the model only arbitrates and writes `reason`. **The model may not name a field the pack does not declare** — constrain the choice to the retrieved list. |
| **Unit conversion & business rules** | `engine/units.py`, factors declared in the pack | Zero model involvement. Editing a factor in the YAML and re-running changes the column. Produce `formula_text` for every conversion. |
| **Ambiguity handling** | `engine/gate.py` | Two thresholds, **stated defaults 0.90 / 0.60**, fitted against the hand-labelled golden set. ⚠ `ps06.needs_review` is uncorrelated with `extraction_confidence` and cannot calibrate anything — never claim it did. `missing` is written and shown, never dropped. A value without provenance must be impossible to construct — enforce it in the pydantic model, not in a comment. |
| **Feedback-driven learning** | `memory/`, `engine/rounds.py` | `PATCH /api/mappings/{id}` writes a precedent and returns `learned: true` with a `learned_message`. The next run on the same source label resolves from the precedent **with no model call**, and the round report shows the delta. |

---

## 4. Agentic AI — where it is, and where it is not

Three agents, each with one narrow inspectable job, inside a state machine whose edges we
drew (LangGraph, checkpoint per node, fan-out inside Extract and Map, retry with backoff,
resume rather than restart).

- **Extractor** — hard pages only (scans, narrative, broken tables, footnotes) → facts with page + bbox.
- **Mapper** — a fact + retrieved candidates → chosen field + reason + confidence.
- **Verifier** — a resolved value + its source snippet → supported or not, + reason. Its
  rejections are shown as first-class results, never silently dropped.

**Not agents, on purpose:** ingestion, unit conversion, the gate, the feedback write-back,
the export. If you are tempted to add a fourth agent, the answer is no.

Model settings: **pinned model version**, **structured output with an enforced response
schema**, per-document token budget, hard timeout, exponential backoff on 429.

**Temperature is provider-dependent, and getting it wrong is a 400, not a warning.**

| Dialect | Sampling | What carries determinism |
|---|---|---|
| OpenAI (incl. OpenRouter, Vertex's compat endpoint) | send `temperature=0` | temperature + pinned model + structured output |
| Anthropic | **send nothing** | pinned model + structured output + pinned `effort` |

On current Claude models `temperature`, `top_p` and `top_k` are **removed**: Fable 5/5.1,
Opus 5.5/5/4.8/4.7 and Sonnet 5 return a 400 for any value, and Sonnet 5.5 / Haiku 5.5
reject any non-default value — so `temperature=0` fails there too. `seed` does not exist in
the Anthropic API at all. The anthropic dialect omits the field entirely.

**Record what was sent, never what was intended.** `RoundReport.sampling` is
`"temperature=0"` or `"not-sent: removed by provider"`. Printing "temperature 0" for a
provider that cannot accept it is a false claim about a controlled variable.

### The three lanes when something goes wrong — say the same thing the code does

- **`Unavailable`** (no key, timeout, rate limit, provider down, non-conforming reply after
  one retry) → **`review`**. A human sees the field. The honest stage answer to "what
  happens when the model is down?" is *"the field reaches a human"*, not *"the field
  disappears"*.
- **A model naming a field the pack does not declare** → **`missing`**, with the reason.
  That is the system refusing to invent, and it is shown as a result, not hidden.

---

## 5. Config and secrets — never a file at runtime

Two resolvers that deliberately differ:

```
control(key)      session -> database -> env -> default        # chains freely
secret_for(id)    session -> database -> env SEED (once)       # then STOPS
```

- Env is a **seed** for secrets, not a fallback. After the first resolution the database
  owns the value, labelled `env-seed`.
- **An explicit empty value is a value** — a stored `""` stops the chain, or clearing a
  key would be impossible.
- Last-known-good applies to controls only, never to secrets.
- Every resolved value carries a `source` the Settings page displays.
- Never bake a credential or a setting into a container image, and never read `.env`
  from inside a library — only entry points load it.

Providers are **four rows of data, two wire dialects** (`openai`-style and
`anthropic`-style): OpenAI, OpenRouter (bring-your-own-model), Google/Vertex, Anthropic.
The provider module makes **no network call** so both dialects can be tested with no key
and no wifi. A listed model is not a callable one — `model-unavailable` is its own named
error state, as are `no-key`, `bad-key`, `rate-limited`, `timeout`, `provider-down`.

---

## 6. Error containment — errors stop where they start

No layer raises across its seam. Every boundary returns a typed result.

| Failure | Behaviour |
|---|---|
| One corrupt file | that document is `unsupported`/`error`; the batch continues |
| Provider outage / quota | `intelligence/` returns `Unavailable`, never raises. Precedent matches still resolve; the rest queue. Health says `degraded` with the reason |
| Malformed pack | the run is **blocked before any document is read**, naming the file and line |
| A quoted rule no longer matches its source | `test_packs.py` red in CI; the pack cannot ship |
| Verifier rejects a field | the field is **dropped, not downgraded** — there is no low-confidence claim |

---

## 6b. Deferred features must have seams

Several capabilities are deliberately out of the MVP (BigQuery, Firestore, Document AI,
Eventarc fan-out, SSE, auth, maker-checker, round-3 promotion, a second pack, Vertex).
**Every one of them must be addable later by swapping one implementation behind an
interface that exists today** — see the table in `README.md` §9. So:

- Write the interface even where there is exactly one implementation.
- The pipeline entry point takes **one document**, never a list, so fan-out is a wrapper.
- `tenant_id` is a parameter and a column **everywhere now**, defaulted to `"demo"`.
- Storage goes through `Repository`; config through `ConfigStore`; scanned PDFs through one
  function signature.
- **If adding a deferred item would later require changing a signature in more than one
  file, the seam is wrong — fix the seam, not the feature.**

## 7. House style

- Python 3.11+, `from __future__ import annotations`, pydantic v2 for every boundary type,
  `ConfigDict(extra="forbid")` on anything parsed from outside.
- Pure functions in `engine/`. I/O at the edges.
- A docstring on a module says **why it exists and what it refuses to do**, not what the
  functions are named.
- Comments only where the reason is not visible in the code — especially where a default
  deliberately points the unsafe way.
- Tests are named for the behaviour they protect, not the function they call:
  `test_the_fixture_is_not_mostly_noise`, not `test_build_fixture`.
- No new dependency without a line in the PR saying what it replaced.

---

## 8. Before you say you are done

- [ ] `pytest backend/tests -q` green, **including the five law tests**
- [ ] The frontend runs against it with `VITE_USE_MOCK=false` and no console errors
- [ ] A document end-to-end: upload → mapped → one field flagged → fixed → re-run resolves it with no model call
- [ ] Every value in the output has a `source_location`
- [ ] `grep -ri "APY\|money market\|<any bank name>" backend/engine backend/adapters backend/api` returns nothing
- [ ] No key, `.env`, or service-account JSON in the diff

---

## 9. Things that will be asked on stage, and the honest answer

| Question | Answer |
|---|---|
| "Where is the AI?" | Three agents — extractor, mapper, verifier — inside a LangGraph state machine. Everything else is deterministic on purpose, because unit correctness is a scored criterion. |
| "How do we know it didn't hallucinate this number?" | Click the cell. Page, bounding box, the rule that fired, the model and prompt version, and who approved it. |
| "Does it work in another domain?" | Second pack, same engine, zero code change — and a test that goes red if a domain word leaks into the engine. |
| "Does it actually learn?" | Three round reports side by side, with the controlled variables listed. The improvement came from precedents, and 47 fields in round 2 used no model at all. |
| "What happens when the model is down?" | It degrades: precedents still resolve, the rest queue for review, and the banner says so. A run always produces a result and an honest account of itself. |
