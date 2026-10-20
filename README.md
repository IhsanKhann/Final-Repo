
# Canon — Cross-Source Data Standardization & Transformation Agent

**National AI Hackathon '26 · Problem Statement PS-12 · Team: Ihsan, Ali, Tahreem**

Messy documents in, one clean validated table out, and every number in it points back at
the page it came from. The meaning comes from the customer's own rulebook, never from us.
Three agents propose; a deterministic backbone decides; the analyst corrects; the next
round measurably improves.

**This file is the standard.** Everything in it is agreed. If your lane doc and this file
disagree, this file wins. Read this, then read your own lane doc:

| Lane | Doc | Owner |
|---|---|---|
| Infrastructure, deployment, database, credentials | [`docs/LANE_ALI_INFRA.md`](docs/LANE_ALI_INFRA.md) | Ali |
| Frontend, journeys, wiring, testing & eval | [`docs/LANE_TAHREEM_FRONTEND.md`](docs/LANE_TAHREEM_FRONTEND.md) | Tahreem |
| Engine, agents, API, packs | [`docs/LANE_IHSAN_BACKEND.md`](docs/LANE_IHSAN_BACKEND.md) | Ihsan |
| Rules for AI coding agents | [`CLAUDE.md`](CLAUDE.md) | everyone |

---

## 1. The problem statement, verbatim

> ### PROBLEM STATEMENT PS-12 — Cross-Source Data Standardization & Transformation Agent
> **Difficulty:** Hard  |  **Category:** Data Engineering / NLP
>
> **The Problem**
> Organizations that aggregate data from hundreds of external sources face a fundamental
> standardization challenge. Different companies report equivalent information using
> different layouts, terminology, units of measurement, table structures, narrative
> formats, footnotes, and disclosure practices. Analysts must manually interpret source
> content, convert as-reported values into standardized formats, map information to
> approved fields, and apply business rules or conversion factors. This increases
> processing time, creates dependency on analyst judgment, and raises the risk of
> inconsistency — particularly for unstructured text, incomplete tables, non-readable
> PDFs, and complex domain-specific reporting.
>
> **Your Challenge**
> Build an agentic AI pipeline that ingests documents from diverse external sources,
> automatically identifies reportable data fields despite varying formats and terminology,
> normalizes values (unit conversions, naming conventions, field mappings), and outputs a
> standardized, validated dataset. The agent should handle ambiguous or missing data by
> flagging it for human review rather than guessing, and should improve its mapping
> accuracy over time through analyst feedback.
>
> **Technical Requirements**
> - Multi-format ingestion: PDFs (text and scanned), HTML pages, spreadsheets, and narrative disclosures
> - Intelligent field mapping: recognize equivalent data points across different reporting styles and terminologies
> - Automated unit conversion and normalization with configurable business rules
> - Ambiguity handling: flag low-confidence mappings for human review instead of silent errors
> - Feedback-driven learning: analyst corrections feed back into the mapping model for continuous improvement
>
> **Suggested GCP Tech Stack**
> Google Cloud Document AI, Vertex AI (Gemini), Cloud Run, BigQuery, Dataflow, Cloud Storage
>
> **Sample Dataset**
> No new dataset — reuse `ps01_documents_metadata.csv` (200 documents with varying types
> and sources) or `ps06_sample_rate_sheets.csv` (150 records with extraction confidence scores)
>
> **Evaluation Criteria**
> Field mapping accuracy, unit conversion correctness, reduction in manual standardization
> effort, improvement rate from feedback loop

Both datasets are in [`data/samples/`](data/samples/), and **only** these two — the other
problem statements' files are not in this repo. `ps06` is the primary one: 150 records,
6 institutions, 6 product types, and 33 rows flagged `needs_review` (22%).

⚠ **Two measured facts about the samples that change how we build.** Read
[`data/samples/DATASETS.md`](data/samples/DATASETS.md) before you rely on either file.
First, `ps06.needs_review` is **uncorrelated** with `extraction_confidence` (flagged rows
span 0.61–0.99, unflagged span 0.60–0.99), so it cannot calibrate our thresholds and we
never claim it did — accuracy comes from a hand-labelled golden set of 30 rows. Second,
**neither file contains actual documents**; both are already-extracted tables. We generate
our source documents from `ps06` rows, one institution per format, each using different
terminology for the same quantities — which is precisely the problem the statement
describes.

---

## 2. The five laws

Not principles on a slide. Each one is a test that goes red.

| # | Law | Enforced by |
|---|---|---|
| **I** | **The backbone is deterministic.** No model call may occur inside `engine/`. Proposals enter from outside as data. | `tests/test_no_model_call_in_engine.py` |
| **II** | **Meaning lives only in the pack.** No domain proper noun in `engine/`, `adapters/`, `api/` — only in `packs/`. The scanner carries a positive control so a broken scanner cannot read as a clean engine. | `tests/test_engine_is_domain_agnostic.py` |
| **III** | **Nothing is invented.** Every pack declaration is `QUOTED` (doc + page + verbatim quote, checked against the real file), `AUTHORED` (mandatory `because`), or `MEASURED` (count + the pattern that produced it). A mapping with no pack rule and no analyst precedent behind it can never be auto-accepted. | `tests/test_packs.py` |
| **IV** | **The export is a render, not a generation.** Same data in, byte-identical file out. No model call in the export path. | `tests/test_render_is_byte_identical.py` |
| **V** | **Three states, never two.** `auto` / `review` / `missing`. A boolean forces the interesting middle case into one of the two wrong bins. | `engine/gate.py` |

These are ported from **Preflight**, where they already hold under 137 passing tests.
Reusing proven discipline is the reason this is buildable in the time we have.

---

## 3. Architecture

Eight layers, each independently debuggable, each with a typed boundary. Two rails run
*beside* the stack rather than inside it: the customer's domain packs, and observability.

```
  ┌─ PACKS ─┐                                                    ┌─ OBSERVE ─┐
  │ customer│   ┌──────────────────────────────────────────┐     │ logs      │
  │ YAML    │   │ L1  EXPERIENCE        React + Vite + TS  │     │ run       │
  │ QUOTED  │   │     10 screens, journey-driven  [Tahreem]│     │ ledger    │
  │ AUTHORED│   └──────────────────┬───────────────────────┘     │ token     │
  │ MEASURED│   ┌──────────────────▼───────────────────────┐     │ budget    │
  │         │   │ L2  IDENTITY & POLICY                    │     │ round     │
  │ no code │   │     tenant_id · roles · quota · audit    │     │ reports   │
  │ no      │   └──────────────────┬───────────────────────┘     │           │
  │ prompts │   ┌──────────────────▼───────────────────────┐     │ wraps     │
  │         │   │ L3  API SEAM          FastAPI :8000      │     │ every     │
  │         │   │     the 12 endpoints, thin by rule       │     │ layer     │
  │         │   └──────────────────┬───────────────────────┘     │           │
  │ feeds   │   ┌──────────────────▼───────────────────────┐     │           │
  │ L4 ───► │   │ L4  ORCHESTRATION     the spine you drew │     │           │
  │ L5 ───► │   │     checkpoint per node · fan-out · retry│     │           │
  │ L6 ───► │   └──────────────────┬───────────────────────┘     │           │
  │         │   ┌──────────────────▼───────────────────────┐     │           │
  │         │   │ L5  INTELLIGENCE      ★ MAY ONLY PROPOSE │     │           │
  │         │   │     extractor · mapper · verifier        │     │           │
  │         │   └──────────────────┬───────────────────────┘     │           │
  │         │   ┌──────────────────▼───────────────────────┐     │           │
  │         │   │ L6  DETERMINISTIC RESOLUTION  ✓ BACKBONE │     │           │
  │         │   │     pack rules · units · gate · ledger   │     │           │
  │         │   │     NO MODEL CALLS. Only layer that may  │     │           │
  │         │   │     write to the gold table.             │     │           │
  │         │   └──────────────────┬───────────────────────┘     │           │
  │         │   ┌──────────────────▼───────────────────────┐     │           │
  │         │   │ L7  MEMORY & FEEDBACK       per tenant   │     │           │
  │         │   │     precedents · round reports · promote │     │           │
  │         │   └──────────────────┬───────────────────────┘     │           │
  │         │   ┌──────────────────▼───────────────────────┐     │           │
  │         │   │ L8  DATA & COMPUTE              [Ali]    │     │           │
  │         │   │     GCS · BigQuery · Cloud Run · Eventarc│     │           │
  └─────────┘   └──────────────────────────────────────────┘     └───────────┘
>>>>>>> b742aed1b2abf3113fb78d18e39db7bcbac6a1a4
```

### The pipeline inside L4–L6

```
 SOURCES ──► INGEST ──► EXTRACT ──► MAP ──► CONVERT ──► VERIFY ──► GATE ──┐
  pdf/html    code       agent 1    agent 2   code       agent 3    code  │
  xlsx/csv    parse      hard       picks     units      scores     0.90  │
  narrative   hash       pages      field     rulepack   + reason   0.60  │
                                      ▲                                   ▼
                                      │                            HUMAN TRAY
                              MAPPING MEMORY ◄───── learn ──────── accept/fix/reject
                              aliases + precedents
```

**Only three stages get an agent.** Ingest and convert are plain code, on purpose:
parsing is not a judgement call, and "unit conversion correctness" is a scored criterion
that a lookup table wins 100% and a model wins 97% inexplicably.

---

<<<<<<< HEAD
## 🚀 Running Locally
=======
## 4. The contract — the frontend's `types.ts` is law

`Frontend/src/api/types.ts` was written first and **the backend conforms to it.** Do not
rewrite those types to match a document. Vocabulary that is now fixed everywhere,
including inside the Python engine:

| Thing | The agreed form |
|---|---|
| Mapping status | `auto` \| `review` \| `missing` \| `approved` \| `rejected` — the third lane is **`missing`**, never "refused" |
| Batch stage | `uploading` \| `ingesting` \| `parsing` \| `mapping` \| `normalizing` \| `validating` \| `ready` \| `failed` |
| PDF location | `{ type:'pdf', page, bbox:[x,y,w,h] }` — **bbox normalized 0–1**, not absolute points |
| Sheet location | `{ type:'sheet', sheet, cell }` e.g. `"B12"` |
| Text location | `{ type:'text', start, end }` character offsets |
| Conversion | `{ factor, rule_id, formula_text }` — `formula_text` is human-readable, shown in the UI |
| Confidence | float `0–1` |

### The twelve endpoints

All already called by `Frontend/src/api/endpoints.ts`. The backend implements exactly these.

```
GET    /api/health                                 HealthStatus
GET    /api/home/stats                             HomeStats
GET    /api/batches                                Batch[]
POST   /api/batches                                CreateBatchPayload -> Batch
GET    /api/batches/{id}                           Batch
GET    /api/batches/{id}/events                    SSE AgentEvent   (MVP: poll)
POST   /api/batches/{id}/cancel                    Batch
GET    /api/batches/{id}/records?page&per_page     PaginatedResponse<DatasetRecord>
GET    /api/batches/{id}/export?format&audit       file
GET    /api/documents/{id}                         Document
GET    /api/documents/{id}/mappings                Mapping[]
PATCH  /api/mappings/{id}                          MappingPatchPayload -> MappingPatchResponse
POST   /api/mappings/bulk-accept                   BulkAcceptPayload -> BulkAcceptResponse
GET    /api/review-queue                           ReviewQueueItem[]
GET    /api/packs  ·  GET/PUT /api/packs/{id}      SchemaPack
GET    /api/insights                               Insights
GET    /api/settings  ·  PATCH /api/settings       config layer (new, see §6)
```

`MappingPatchResponse` carries `learned: boolean` and `learned_message` — **that is the
feedback loop surfacing in the UI**, and it already exists in the types.

---

## 5. Repo layout

```
final-project/
├─ README.md                   ← this file, the standard
├─ CLAUDE.md                   ← rules for AI coding agents
├─ docs/
│   ├─ LANE_ALI_INFRA.md
│   ├─ LANE_TAHREEM_FRONTEND.md
│   └─ LANE_IHSAN_BACKEND.md
├─ data/samples/               ps01 + ps06 + DATASETS.md
├─ Frontend/                   React + Vite + TS          [Tahreem] — already on main
├─ backend/
│   ├─ packs/                  DOMAIN DATA — customer YAML, no code, no prompts
│   ├─ engine/                 THE BACKBONE — no model calls, no domain nouns
│   │   ├─ contracts.py        pydantic mirror of types.ts
│   │   ├─ config.py           two-resolver config layer (§6)
│   │   ├─ packs.py  units.py  resolve.py  gate.py  ledger.py  rounds.py  render.py
│   ├─ adapters/               csv · xlsx · html · pdf_text · pdf_scan
│   ├─ intelligence/           PROPOSERS ONLY — providers/{openai,openrouter,google,anthropic}
│   ├─ memory/                 per-tenant precedents
│   ├─ api/                    FastAPI, thin by rule
│   ├─ eval/                   golden set · scorer · round reports
│   └─ tests/                  the five laws
├─ infra/                      Terraform (from alibranch)  [Ali]
└─ .env.example
```

### Branches

| Branch | Contents | Status |
|---|---|---|
| `main` | Frontend (DataSync), docs, backend | the trunk — everything merges here |
| `alibranch` | Terraform, Express reference, Doc AI + BigQuery services | **keep the Terraform**, retire the Express app (we run one Python backend) |

---

## 6. The config layer — credentials survive redeploys

**No credential or setting is ever baked into a container image or read from a file at
runtime.** They live in a database, and the Settings page changes them live.

```
control(key)      session -> database -> env -> default        # chains freely
secret_for(id)    session -> database -> env SEED (once)       # then STOPS
```

- A **control** is a policy decision (provider, model, max tokens, timeout, the two gate
  thresholds). Chaining to env then a default is correct.
- A **secret** is not. Env is a **seed**: the first resolution with nothing stored
  promotes the env value into the store labelled `env-seed`, and after that the store owns
  it and env is never read again. Without this rule the key you paste dies, the stale one
  in `.env` quietly answers, and the Health page still says connected.
- **An explicit empty value is a value.** A stored `""` stops the chain exactly like a key
  does, or clearing a key would be impossible.
- **Last-known-good covers controls only, never secrets** — it would resurrect a key the
  operator had just revoked.
- Every resolved value carries its `source` (`session` / `db` / `env-seed` / `default` /
  `last-known-good` / `unset`) and the Settings page shows it next to the value.

Store: `config(tenant_id, key, value, source, updated_by, updated_at)` and
`secrets(tenant_id, id, value_enc, source, updated_by, updated_at)`.
**SQLite locally → Firestore in cloud, one interface, swapped by one env var.**

### Providers: four rows, two dialects, no HTTP in the module

| Provider | Dialect | Why |
|---|---|---|
| **OpenAI** | OpenAI chat completions | What we run inference on. Key in hand. |
| **OpenRouter** | OpenAI chat completions | **Bring your own model** — a customer pastes their own key and picks any model it reaches; we can A/B two models on the same documents without touching code. Its catalogue needs no key, so the picker populates before anyone signs in. |
| **Google / Vertex** | OpenAI compatibility endpoint | The suggested stack; what the GCP credits pay for. |
| **Anthropic** | Anthropic Messages | The second dialect — proves the adapter is real, not a wrapper around one SDK. |

There is no router per provider: a provider is a row of data and the only polymorphic
thing is the wire dialect. **A listed model is not a callable one** — `/models` will offer
models that 404 for new keys, so `model-unavailable` is its own error state. Every
provider failure maps to a named state: `no-key`, `bad-key`, `model-unavailable`,
`rate-limited`, `timeout`, `provider-down`.

---

## 7. Run it locally

### Frontend (works today, with mocks, no backend needed)
>>>>>>> b742aed1b2abf3113fb78d18e39db7bcbac6a1a4

### 1. Start the Node.js Backend
```bash
<<<<<<< HEAD
cd doc-standardization-pipeline/backend
npm install
npm start
```
> Running on **http://localhost:8080**  
> Health check: `http://localhost:8080/api/health`

### 2. Start the Frontend
```bash
cd doc-standardization-pipeline/frontend
npm install
npm run dev
```
> Running on **http://localhost:5173**  
> Automatically proxies `/api` calls to the Node.js backend.
=======
cd Frontend
npm install
npm run dev            # http://localhost:5173
```

`Frontend/.env`:
```
VITE_USE_MOCK=true                  # flip to false once the backend is up
VITE_API_URL=http://localhost:8000
```

### Backend (session 2)

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
cp ../.env.example ../.env                          # seed values only
uvicorn api.main:app --reload --port 8000
```

Then set `VITE_USE_MOCK=false` and restart the Vite dev server.

**No API key is needed to start the backend.** With no key configured the pipeline still
runs: everything with a precedent resolves deterministically, the rest goes to the review
tray, and the Health page says `degraded` with the reason. A run always produces a result
and an honest account of itself.

---

## 8. Credentials — who gets what

| Credential | Needed for | Who obtains it | Where it goes |
|---|---|---|---|
| `OPENAI_API_KEY` | Inference (mapper, extractor, verifier) | Ihsan — **have it** | `.env` as a seed → promoted into the config DB on first run |
| `OPENROUTER_API_KEY` | Bring-your-own-model demo | optional, free tier | Settings page at runtime, never a file |
| GCP project + billing | Everything cloud | Ali | `gcloud config` |
| Service account JSON | Cloud Run, GCS, BigQuery, Doc AI | Ali | Secret Manager; locally `GOOGLE_APPLICATION_CREDENTIALS` |
| `DOCAI_PROCESSOR_ID` | Scanned PDFs | Ali (from `terraform apply`) | config DB, not the image |
| Bucket + dataset names | Storage targets | Ali (from `terraform apply`) | config DB |

**Nothing above goes in git.** `.env` is gitignored; `.env.example` holds empty keys only.

---

## 9. Coverage against PS-12

| Requirement | MVP | What is real | What is left |
|---|---|---|---|
| **Multi-format ingestion** | 85% | CSV/XLSX (pandas, openpyxl), text PDF (pdfplumber, page + bbox), HTML (selectolax), narrative via extractor, **scanned PDF via PyMuPDF rasterize → GPT-4o vision** (no system deps, works on Windows) | Document AI swap-in; >15-page async batch route |
| **Intelligent field mapping** | 90% | Deterministic candidate retrieval over pack synonyms + precedents, LLM arbitration only where no candidate wins, reason on every mapping, constrained to declared fields | Embedding retrieval for unlisted terms; 2nd domain pack |
| **Unit conversion + business rules** | 100% | Table-driven converter whose factors are declared in the pack, with `formula_text`. Edit pack → re-run → column changes | — |
| **Ambiguity handling** | 100% | Three lanes on stated thresholds (0.90 / 0.60), fitted against the hand-labelled golden set; `missing` shown, never silently dropped; no value constructible without provenance | maker-checker on high-materiality fields |
| **Feedback-driven learning** | 80% | Rounds 1 & 2: correction writes a precedent, re-run applies it with **no model call**, round report shows the delta | Round 3 promotion into a proposed pack v2 |

**≈90% of the technical requirements; all four evaluation criteria measurable.** The gap
is cloud-deployment-shaped, not capability-shaped.

### Deferred on purpose — and the seam that makes each one a drop-in

Nothing is cut without a seam. **Every deferred item is a swap behind an interface that
exists from the first hour**, which is the only thing that makes deferring safe. Write the
interface even where there is one implementation.

| Deferred | Seam that exists from day one | Cost to add later |
|---|---|---|
| BigQuery / GCS storage | `Repository` interface; `SqliteRepository` today | a second class, one env var |
| Firestore config store | `ConfigStore` interface; `SqliteStore` today | Ali's class, one env var |
| Document AI | `pdf_scan.py` signature `(bytes, mime) -> ExtractedFact[]` | one module body |
| >15-page async batch | the router already branches on page count | one branch |
| Eventarc / Pub/Sub fan-out | the pipeline entry point takes **one document**, never a list | a job wrapper, no engine change |
| SSE live events | events already written to an `EventLog`; UI polls one hook | one endpoint, one hook |
| Auth / multi-tenant | `tenant_id` is a column and a parameter **everywhere now**, defaulted to `"demo"`; all calls go through one `apiFetch` | middleware + one header |
| Maker-checker | ledger already carries `reviewed_by` **and** `approved_by` | a gate rule reading pack materiality |
| Round 3 promotion | precedents already counted per `(source_label, field)` | a query and a `PROPOSED` pack entry |
| Second domain pack | Law II keeps the engine clean | writing a YAML file |
| Vertex / Gemini | provider row + dialect already exist | a config change, no code |
| Document viewer | one `<Evidence source={...}/>` switching on `source_location.type`; `pdfjs-dist` already a dependency | one component body |

**The rule:** if adding a deferred item would later require changing a function signature
in more than one file, the seam is wrong — fix the seam now, not the feature.

### Where the "agentic AI" is, precisely

Judges will ask. The answer is three agents with narrow, inspectable jobs, inside a graph
whose edges we drew:

| Agent | Input | Output | Why it must be an agent |
|---|---|---|---|
| **Extractor** | hard pages — scans, narrative, broken tables, footnotes | `ExtractedFact[]` with page + bbox | layout genuinely defeats parsers |
| **Mapper** | a fact + retrieved candidates from pack & memory | chosen field + `reason` + confidence | recognising *unlisted* terminology is the judgement the problem statement is about |
| **Verifier** | resolved value + its source snippet | supported / not, + reason | catches the mapper; its rejections are shown, not hidden |

Plus a **state machine** (LangGraph) with a checkpoint per node, parallel fan-out inside
Extract and Map, retry with backoff, and resume-not-restart. Not a free-roaming
orchestrator: one that picks its own route takes a different path on stage than it took in
rehearsal.

---

## 10. The three-round feedback loop

```
ROUND 1 ──► REVIEW ──► ROUND 2 ──► REVIEW ──► ROUND 3 ──► VERIFIED OUTPUT
pack only   analyst    pack +      smaller    promoted    gate ALLOWED
            fixes      memory      tray       rules       + sign-off
   │           │          │           │          │
   └───────────┴──► precedents ───────┴──► promotions ──► proposed pack v2
```

- Round 1 runs on the pack alone. Expect ~22% flagged on `ps06`.
- Each correction writes one precedent, tagged `ANALYST` — ranks above a model proposal,
  below a `QUOTED` pack rule.
- Round 2 re-runs the same documents. Precedent matches resolve **with no model call at
  all** — faster, cheaper, provably identical to what the analyst chose.
- Round 3: a term corrected the same way three times is **proposed** as a pack synonym.
  The customer accepts it. *The system proposes, the customer authors.* That line never moves.
- **What must not change between rounds:** documents, pack version, model, temperature,
  prompt version. All five are recorded in the round report. If any differ, the comparison
  is void and the UI says so instead of showing a number.

---

## 11. Demo script (90 seconds that answer the whole statement)

1. **Show the pack.** "This is the customer's rulebook, with a page citation on every rule.
   We did not write it, and the engine has never heard of a bank."
2. Drop in two rate sheets that report the same thing differently, plus a scanned PDF and a spreadsheet.
3. **Gold table:** one schema, four sources, units aligned.
4. **Click a cell.** Evidence opens on page 4, box highlighted, with the rule that fired and the reason.
5. **Open the tray.** Fix one mapping. "Watch what that does."
6. **Re-run.** Round 2 beside round 1: accuracy up, tray smaller, cost down, 47 fields resolved with no model call.
7. Close on the effort-saved counter and the revenue streams.

Steps 1, 4 and 6 are the ones nobody else in the room will have. Protect the time.

---

## 12. Business model

Price the unit of work, not the seat. The moat is the pack plus the memory: both are
per-customer, both compound with every correction, and leaving means authoring the
rulebook again from zero.

| Tier | Price | Pages/mo | Gets | Enforced in MVP |
|---|---|---|---|---|
| Free | $0 | 100 | 1 pack, review console, CSV export | **yes — page quota at ingest** |
| Pro | $499/mo | 5,000 | Unlimited packs, API, BigQuery export, 3 seats, round reports | slide only |
| Enterprise | from $4k/mo | unlimited | Own schema registry, SSO, maker-checker, audit export, replay, SLA | slide only |

**Five revenue streams:** subscription · usage overage ($0.04/page) · **pack authoring**
(paid onboarding where we co-author pack v1 from their documents — the stickiest part) ·
embedded API for aggregators · compliance add-on (audit export, retention, replay).

**ROI line:** an analyst standardizes ~40 fields an hour. At 90% auto-accept across 5,000
pages a month you hand back hundreds of analyst hours for $499. The dashboard computes it
from the pipeline's own counters, so the number is measured, not estimated.

---

## 13. Working agreement

- **Commit to your own lane's folders.** Ali owns `infra/`, Tahreem owns `Frontend/`,
  Ihsan owns `backend/`. Shared files (`README.md`, `CLAUDE.md`, `.env.example`) change by
  agreement, in a commit that says so.
- **Never commit `.env`, a service-account JSON, or any key.** If one lands in git, rotate
  it immediately — do not just delete the file.
- **The contract changes in one place.** If `types.ts` must change, say so in the group
  before editing, because it moves both the frontend and the backend.
- **Small commits, present tense, one concern each.** `feat: pack loader with provenance
  validator`, not `updates`.
- Rebase on `main` before you push. If you hit a conflict in someone else's lane, stop and
  ask them — do not resolve it yourself.
>>>>>>> b742aed1b2abf3113fb78d18e39db7bcbac6a1a4
