# Canon

**A cross-source data standardization agent. Every value in the output points back at the
page, cell or character span it came from.**

[![License: BUSL-1.1](https://img.shields.io/badge/license-BUSL--1.1-00529b.svg)](LICENSE)
[![Status: active development](https://img.shields.io/badge/status-active%20development-2da44e.svg)](#where-this-is-going)
[![Python 3.11](https://img.shields.io/badge/python-3.11-3776ab.svg)](backend/requirements.txt)
[![React + TypeScript](https://img.shields.io/badge/react-TypeScript-3178c6.svg)](Frontend/package.json)

Organisations that aggregate data from hundreds of external sources all hit the same wall:
every source reports equivalent information with different layouts, terminology, units and
disclosure practices, so an analyst has to interpret each one by hand.
([PS-12 verbatim, with the five technical requirements →](docs/PROBLEM_STATEMENT.md))

Canon ingests those documents, maps each field onto one the **customer** declared in a YAML
rulebook, converts units using factors the **customer** declared, flags what it is unsure
about for a human instead of guessing, and learns from every correction.

Three agents propose. A deterministic backbone decides. The analyst corrects. The next run
is measurably better — **3 corrections resolved 68 fields**, measured below.

### Where this is going

Canon began as a build at the **National AI Hackathon '26** against
[Problem Statement PS-12](docs/PROBLEM_STATEMENT.md), by
[Ihsan](https://github.com/IhsanKhann), [Tahreem](https://github.com/tahreem05) and
[Ali](https://github.com/investpro599-a11y) — [what each of us built →](CONTRIBUTORS.md).

**It is no longer a hackathon deliverable.** It is in continued development, and being
scaled deliberately rather than quickly: the [*What is NOT true yet*](#what-is-not-true-yet)
section below is permanent, and it is the roadmap. An item leaves it when a test or a
measurement moves it, not when it feels done — because a confident number with nothing
behind it is the exact failure this product exists to prevent.

---

## Architecture

One load-bearing idea: **the layer that can be wrong may only propose, and the layer that
decides cannot call a model.** Everything else follows from it.

```
   CUSTOMER RULEBOOK                                               EVIDENCE
  ┌─────────────────┐   ┌────────────────────────────────┐   ┌──────────────────┐
  │  packs/*.yaml   │   │  SOURCES                       │   │  append-only     │
  │                 │   │  pdf · scan · html · xlsx      │   │  ledger          │
  │  fields         │   │  csv · narrative prose         │   │                  │
  │  synonyms       │   └───────────────┬────────────────┘   │  one row per     │
  │  conversions    │                   │                    │  cell, per run   │
  │  precedence     │   ┌───────────────▼────────────────┐   │                  │
  │  materiality    │   │  ADAPTERS         no model     │   │  hash-chained,   │
  │  ambiguity      │   │  one per format, no shared     │   │  tamper-evident  │
  │                 │   │  state. Emits facts WITH       │   │                  │
  │  every rule     │   │  provenance and a record key.  │   │  page · bbox ·   │
  │  carries its    │   └───────────────┬────────────────┘   │  cell · offsets  │
  │  own provenance │                   │                    │  rule · model ·  │
  │                 │   ┌───────────────▼────────────────┐   │  prompt version  │
  │  QUOTED  → doc  │   │  INTELLIGENCE   ★ MAY ONLY     │   │  reviewed_by ·   │
  │  AUTHORED→ why  │   │                   PROPOSE      │   │  approved_by     │
  │  MEASURED→ count│   │  extractor · mapper · verifier │   └────────┬─────────┘
  │                 │   │  constrained to declared       │            │
  │  data only —    │   │  fields. Cannot invent one.    │            │ writes
  │  no code,       │   └───────────────┬────────────────┘            │
  │  no prompts     │      Proposal │ Unavailable                     │
  └────────┬────────┘               │  (never raises across a seam)   │
           │  declares              ▼                                 │
           ├───────────▶┌────────────────────────────────┐◀───────────┘
           │            │  DETERMINISTIC BACKBONE        │
           │            │  ✓ NO MODEL CALL, EVER         │
           │            │                                │
           │            │  units · resolve · gate        │
           │            │  validations · render          │
           │            │                                │
           │            │  authority order:              │
           │            │  PACK_QUOTED > PACK_AUTHORED   │
           │            │       > ANALYST > MODEL        │
           │            └───────────────┬────────────────┘
           │                            │
           │              ┌─────────────┼─────────────┐
           │              ▼             ▼             ▼
           │          ┌───────┐    ┌────────┐   ┌──────────┐
           │          │ auto  │    │ review │   │ missing  │  three lanes,
           │          │ ≥0.90 │    │  tray  │   │ nothing  │  never a boolean
           │          └───┬───┘    └────┬───┘   │ claimed  │
           │              │             │       └──────────┘
           │              ▼             ▼
           │       ┌────────────┐  ┌──────────────────┐
           │       │ GOLD TABLE │  │  HUMAN corrects  │
           │       │ + export   │  │  or assigns      │
           │       └────────────┘  └────────┬─────────┘
           │                                │
           │                                ▼
           │                      ┌──────────────────────┐
           └──────────────────────│  MEMORY              │
               precedent, ranked  │  (tenant, label)     │
               ANALYST, resolves  │       → field        │
               with NO model call │  compounds per       │
                                  │  customer            │
                                  └──────────────────────┘
```

Eight layers, each independently debuggable, each with a typed pydantic boundary. Layer
detail in [`ARCHITECTURE.md`](ARCHITECTURE.md); the rules agents may not break are in
[`CLAUDE.md`](CLAUDE.md).

---

## Measured

Six generated source documents, through the real HTTP API, from a clean store, with **no
API key configured**. Reproduce with `python -m backend.eval.make_documents` and one
`POST /api/batches`.

| | |
|---|---|
| Documents in | 6 — text PDF, scanned PDF, HTML, XLSX, CSV, narrative prose |
| Fields resolved | **464** → 278 `auto` / 141 `review` / 45 `missing` |
| Records in the gold table | **126** — a document is not a record; one spreadsheet holds 30 |
| Labels that are not fields | 269, counted and **never queued** at a reviewer |
| Model calls | **0** — all 464 resolved deterministically |
| Evidence rows | **463**, one per resolved field, hash-chained; a test mutates one and the chain fails |
| Export | byte-identical across two requests |
| Tests | 493 passing, 3 skipped, 4 failing (stale — see below) |

### Does it actually learn? A controlled comparison

Same six documents, same pack, same model, same prompt version. **Only the precedents
changed.** Zero model calls in either round.

| | auto | review | model calls | precedents applied |
|---|---:|---:|---:|---:|
| **Round 1** — pack only, empty memory | 278 | 141 | 0 | 0 |
| *analyst assigns 3 labels a field* | | | | |
| **Round 2** — identical inputs | **346** | **73** | 0 | **68** |

**Three human decisions resolved 68 fields.** Not re-prompted — resolved from stored
precedents at `ANALYST` authority, with the model never consulted. That is the difference
between learning and rolling the dice twice. Five controlled variables are recorded in
every round report, and it refuses to compute a delta if any of them moved.

### Unit conversion

`Nominal (monthly)` **0.3383** → **4.0596** `interest_rate_annual_pct`, through a ×12 factor
the customer declared, attached to cell `Rates!C12`, carrying the human-readable formula
`× 12 (monthly → annual)`. Edit the factor in the YAML, re-run, the column changes. No model
touches any conversion.

### Against the hand-labelled golden set — 30/30 rows confirmed by two named people

| | |
|---|---|
| Matched | 17 / 30 |
| Field mapping accuracy | **0.4667** |
| Unit conversion correctness | 1.0 — **over one row**; see below |

The 13 misses are **5** scanned-PDF, **5** narrative, **3** pack-vocabulary gaps. One row
matched and was mapped wrong. We publish the denominator, not the headline.

---

## What is NOT true yet

This section exists because a confident number with nothing behind it is the exact failure
this product claims to prevent. Every item below was found by a test or a measurement.

- **No real vision call has ever been made.** The scanned PDF rasterizes and reports
  `Unavailable`, which routes it to review. It does **not** read the scan. In the run above
  it contributes exactly one review-tray row, whose reason reads *"this document was
  rasterized and not read (model-unavailable)"* — which is why 464 fields produce 463
  evidence rows. **Do not demo it as working.**
- **"100% conversion correctness" is one row.** Exactly one confirmed golden row expects a
  conversion. The converter is table-driven and correct; the denominator is 1.
- **Mapping accuracy is 0.4667 and we are not rounding it up.** 10 of the 13 misses are
  structural: no vision, and prose labels that cannot join on a column heading.
- **Three labels never reached the model at all.** `'From'`, `'valid from'` and
  `'Yield (annual)'` are emitted by the documents but declared by no pack synonym, so
  deterministic retrieval found no candidate and the mapper was never asked. That is a real
  weakness, and it is where our system currently ends.
- **The gate thresholds (0.90 / 0.60) are stated defaults, not calibrated.** They cannot be
  fitted against the sample's own review flag, which is uncorrelated with the confidence
  score it would have to correlate with. `thresholds_are_calibrated` is `False` in code.
- **The pack contains no `QUOTED` declaration.** `QUOTED` means the rule appears in the
  customer's own document with a page and a verbatim quote. No such document exists yet, so
  a citation would be a fabrication. The pack is `MEASURED` and `AUTHORED` only — drafted by
  an agent, **accepted by a named human**, which the loader enforces at both levels.
- **Terraform was written and never applied.** The live resources were provisioned with
  `gcloud` and Cloud Build. There is no state file.
- **No tier, quota or billing logic exists.** The business model below is slide only.
- **4 tests fail**, all asserting the golden set is unconfirmed — it now is. Skips are
  named, never silent.

---

## The five laws, and the test that enforces each

Not principles on a slide. Each one is a test that goes red.

| | Law | Enforced by |
|---|---|---|
| **I** | No model call may occur under `engine/`. Proposals arrive as plain data. | `test_no_model_call_in_engine.py` — AST scan, **with a positive control** |
| **II** | No domain noun outside `packs/`. The engine has never heard of a bank. | `test_engine_is_domain_agnostic.py` — the scanner is also run over text that *does* contain the terms, so one broken by a typo cannot read as a clean engine |
| **III** | Nothing is invented. Every rule is `QUOTED`/`AUTHORED`/`MEASURED`, and acceptance names a human and a date. | `test_packs.py` — re-counts every `MEASURED` claim against the real CSV |
| **IV** | The export is a render. Same data in, byte-identical file out. | `test_render_is_byte_identical.py` |
| **V** | Three lanes, never two. The interesting case is the middle one. | `test_the_gate_has_three_lanes.py` |

This codebase's signature failure is a **correct, tested mechanism with nothing calling
it** — it happened three times: a misspelled env var, a ledger with no writer, and two
config controls the pipeline ignored while the UI displayed their values.
`test_every_control_has_a_reader.py` exists for exactly that, and has no exemption list.

---

## Run it

```bash
# Backend. No API key needed: with none configured, everything deterministic still resolves,
# the rest goes to the review tray, and /api/health says `degraded` with the reason.
cd backend
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
python -m backend.eval.make_documents               # generate the six source documents
uvicorn api.main:app --reload --port 8000

# Frontend
cd Frontend && npm install && npm run dev           # http://localhost:5173
```

Also deployed on Cloud Run. Credentials live in a database, never in the image: a key
PATCHed through the Settings page survived three redeploys resolving `source=db`, with no
credential in the container — verified by the infra lane.

---

## Where the AI is, precisely

Three agents with narrow, inspectable jobs, inside a state machine whose edges we drew.

| Agent | Decides | Why it must be a model |
|---|---|---|
| **Extractor** | facts on hard pages — scans, prose, broken tables | layout genuinely defeats parsers |
| **Mapper** | which declared field an unlisted heading means, and why | recognising unlisted terminology *is* the problem statement |
| **Verifier** | whether a resolved value is supported by its source | catches the mapper; its rejections are shown, not hidden |

**Deliberately not agents:** ingestion, unit conversion, the gate, the feedback write-back,
the export. Unit correctness is a scored criterion that a lookup table wins 100% of the time
and a model wins 97% of the time inexplicably.

The model **cannot name a field the pack does not declare** — retrieval constrains the
choice and the backbone rejects anything outside it. A proposal naming a declared field
reaches a human at any confidence rather than being discarded; one naming an undeclared
field is refused outright.

---

## Business model — slide only; nothing below is enforced in code

Price the unit of work, not the seat. The moat is the pack plus the memory: both are
per-customer, both compound with every correction, and leaving means authoring the rulebook
again from zero.

| Tier | Price | Pages/mo |
|---|---|---|
| Free | $0 | 100 |
| Pro | $499/mo | 5,000 |
| Enterprise | from $4k/mo | unlimited |

**Five revenue streams:** subscription · usage overage ($0.04/page) · **pack authoring**
(paid onboarding where we co-author pack v1 from the customer's own documents — the
stickiest part) · embedded API for aggregators · compliance add-on (audit export, retention,
replay).

**ROI:** the pipeline counts auto-accepted fields and multiplies by a configured
minutes-per-field — 417 analyst minutes on the six-document run above, 519 after three
corrections. Computed from its own counters, not estimated.

---

## More detail

| | |
|---|---|
| PS-12 verbatim, the five technical requirements, coverage | [`docs/PROBLEM_STATEMENT.md`](docs/PROBLEM_STATEMENT.md) |
| Rules for AI coding agents; the five laws in full | [`CLAUDE.md`](CLAUDE.md) |
| Layer-by-layer design | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Decisions already made, and why | [`docs/AGREEMENTS.md`](docs/AGREEMENTS.md) |
| The data, and two measured facts that changed how we build | [`data/samples/DATASETS.md`](data/samples/DATASETS.md) |
| The API contract — `types.ts` is law and the backend conforms to it | `Frontend/src/api/types.ts` |
| Per-lane build order and ownership | [`docs/`](docs/) |

---

## Team

Three lanes, run in parallel.

| | | |
|---|---|---|
| **[Ihsan](https://github.com/IhsanKhann)** | architecture · backend · deployment | The deterministic backbone and the rule the system is organised around: the layer that can be wrong may only propose, and the layer that decides cannot call a model. The pack/engine split, the authority order, the three-lane gate, the evidence ledger, precedent memory, and the five laws with the tests that enforce them. |
| **[Tahreem](https://github.com/tahreem05)** | product design · testing · research | The product as the analyst meets it — the Rossum-style review drawer and queue, which is where the hard case lives, plus the user portal and full light/dark/system theming. Ran the testing pass that found the stepper and layout faults, did the PS-12 research the packs were authored against, and is one of the two named people who hand-confirmed all 30 golden-set rows. |
| **[Ali](https://github.com/investpro599-a11y)** | deployment · backend | The path from a working repository to a reachable URL. Vercel build and deploy, the serverless API wrapper, self-contained lambdas, per-step progress over SSE and the live batch pipeline — and a zero-cloud fail-safe extraction path so the demo could not be taken down by a missing credential. |

Ali's 15 commits are on `alibranch`, which was never merged, so **GitHub's contributor list
shows two of the three of us.** That is an artefact of counting only the default branch, not
a record of who did the work. The branch is kept rather than deleted so the work stays
attributable — [full credit, per lane →](CONTRIBUTORS.md).

## License

[**Business Source License 1.1**](LICENSE). The source is public and readable; evaluation,
academic and any non-production use are free; **commercial production use requires a
licence**, and offering Canon or a derivative to third parties as a hosted or embedded
service is not granted. The whole work converts to **Apache-2.0 on 2030-10-20**.

Commercial licensing: [designwithIhsan@gmail.com](mailto:designwithIhsan@gmail.com).
