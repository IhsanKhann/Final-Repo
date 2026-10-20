# Lane: Tahreem — Frontend, Journeys, Wiring, Testing & Eval

**Read [`../README.md`](../README.md) first** — it is the standard and carries the problem
statement. This file is your lane. Where they disagree, the README wins.

Your DataSync app is already on `main` (`daf6a47`) and it is the furthest-along piece of
the project. Ten screens, a clean `api/` layer, and — importantly — **`types.ts` is now the
contract the backend conforms to.** Nobody rewrites your types.

---

## 0. Your one-line job

**Make every one of the five PS-12 requirements visible on a screen, drive the build from
user journeys rather than from components, and own the proof that it works — the end-to-end
tests and the evaluation numbers.**

A judge should be able to watch the screen and name the requirement being satisfied,
without anyone narrating it.

---

## 1. Run it right now

```bash
cd Frontend
npm install          # done once; node_modules is already installed on Ihsan's machine
npm run dev          # http://localhost:5173
```

`Frontend/.env` — the only switch that matters:

```
VITE_USE_MOCK=true                  # today: everything renders from mockData.ts
VITE_API_URL=http://localhost:8000  # flip USE_MOCK to false when the backend is up
```

**You are never blocked on the backend.** `src/api/client.ts` already branches on
`VITE_USE_MOCK` for every call. Build every journey against `mockData.ts` first; the day
the backend lands you change one line in `.env`, restart Vite, and the same screens are
live. If a screen only works with mocks, the bug is in the mock, not the backend — make
`mockData.ts` tell the truth about shapes, including the ugly ones (a `missing` mapping, a
`degraded` health layer, a zero-row batch).

---

## 2. The vocabulary — fixed, everywhere

| Thing | Values |
|---|---|
| `MappingStatus` | `auto` · `review` · `missing` · `approved` · `rejected` |
| `BatchStage` | `uploading` · `ingesting` · `parsing` · `mapping` · `normalizing` · `validating` · `ready` · `failed` |
| `SourceLocation` | `{type:'pdf', page, bbox:[x,y,w,h]}` with **bbox normalized 0–1** · `{type:'sheet', sheet, cell}` · `{type:'text', start, end}` |
| `Conversion` | `{factor, rule_id, formula_text}` — show `formula_text`, e.g. `"× 12 (monthly → annual)"` |
| `confidence` | float 0–1. Render as a percentage, store as a float |

**Three visual states, never two.** `auto` is quiet, `review` is amber and actionable,
`missing` is grey with a reason. If the UI collapses to pass/fail, the three-lane model
dies in the interface and we lose the thing that makes us defensible. `missing` is a
first-class result — it means *we refused to guess* — so it gets a column, not a filter
somebody has to find.

---

## 3. The six journeys

Build in this order. Each journey is done when its acceptance criteria pass against mocks,
and done-done when they pass against the live backend.

---

### J1 — First run: the operator brings their own key
**Covers:** the config layer. **Screens:** Settings → Health. **Why first:** nothing else
can be demonstrated on a laptop without it, and it is the one journey that fails loudly
in front of judges if it is an afterthought.

| Step | Screen | What happens |
|---|---|---|
| 1 | Settings | Provider dropdown: OpenAI · OpenRouter · Google · Anthropic. Model dropdown populates from the provider (OpenRouter's catalogue needs no key) |
| 2 | Settings | Paste an API key → Save |
| 3 | Settings | Each value shows **where it came from**: a small `db` / `env-seed` / `default` / `unset` chip beside it |
| 4 | Health | Provider layer turns green within one refresh, no redeploy, no restart |
| 5 | Settings | Clear the key → Health goes `degraded` with the reason `no-key`, and does **not** quietly go green again |

**Endpoints:** `GET/PATCH /api/settings`, `GET /api/health`

**Acceptance**
- The source chip is visible next to every value. A control showing only its own stored
  value is how every dead settings toggle looks while doing nothing.
- Named error states render distinctly: `no-key`, `bad-key`, `model-unavailable`,
  `rate-limited`, `timeout`, `provider-down`. Never a bare "error".
- A key is never echoed back in full — show `sk-…last4`.
- Changing the key takes effect on the **next** request. Put that sentence on the screen.

**Scenario to demo:** *"Our key just ran out mid-demo."* Paste a new one, Health goes
green, the next run works. No redeploy. That is a 20-second story that sells the whole
config layer.

---

### J2 — The customer's rulebook
**Covers:** "configurable business rules" + the thing that makes us different — *we do not
invent domain knowledge*. **Screen:** Schema.

| Step | What happens |
|---|---|
| 1 | Schema page lists the pack: fields, synonyms, units, validation ranges, conversions, business rules |
| 2 | **Every declaration shows a provenance badge**: `QUOTED` (with document + page + the verbatim quote on hover), `AUTHORED` (with the `because` text), `MEASURED` (with the count) |
| 3 | A `PROPOSED` declaration — drafted by the system from a correction pattern — sits in its own group with **Accept** / **Reject** |
| 4 | Accepting one moves it into the pack as `AUTHORED`, with the correction history as its `because` |

**Endpoints:** `GET /api/packs`, `GET /api/packs/{id}`, `PUT /api/packs/{id}`

**Acceptance**
- A `QUOTED` badge without a visible document + page is a bug.
- `PROPOSED` items are never mixed into the accepted list.
- The page makes the claim legible without narration: *the customer wrote this, not the system.*

---

### J3 — Upload and watch it work
**Covers:** multi-format ingestion. **Screens:** Upload → Batches → batch detail.

| Step | What happens |
|---|---|
| 1 | Pick a pack, drop files: PDF (text), PDF (scanned), XLSX, HTML, CSV, a narrative .txt |
| 2 | Per-file status: `ready` → `uploading` → `processing` → `done` / `error` / `unsupported` |
| 3 | Batch stage advances: `ingesting` → `parsing` → `mapping` → `normalizing` → `validating` → `ready` |
| 4 | An agent activity feed shows `AgentEvent`s: which agent, which step, running/done/error |
| 5 | Batch summary: total fields, auto-approved, needs review, missing |

**Endpoints:** `POST /api/batches`, `GET /api/batches`, `GET /api/batches/{id}`,
`GET /api/batches/{id}/events` (SSE; **MVP: poll every 2 s** — build the hook so swapping
to SSE changes one function), `POST /api/batches/{id}/cancel`

**Acceptance**
- One unsupported file marks **that file** `unsupported` and the batch keeps going. A batch
  that dies because of one bad file is the failure mode this journey exists to prevent.
- The six formats are visibly different in the file list (icon + type), because "multi-format
  ingestion" is a requirement a judge reads off the screen.
- The agent feed names real agents — extractor, mapper, verifier — not "Processing…".

---

### J4 — The review tray
**Covers:** ambiguity handling + human-in-the-loop. **Screens:** Review → Dataset. **This is
the most important screen in the product.**

| Step | What happens |
|---|---|
| 1 | Queue of everything in `review`, sorted by confidence ascending — worst first |
| 2 | Select one → **side-by-side**: source evidence left, proposal right |
| 3 | Left: the document with the bbox highlighted on the right page (PDF), or the cell `B12` highlighted (sheet), or the text span highlighted (narrative) |
| 4 | Right: source label → target field, raw value → converted value, `formula_text`, confidence, the agent's `reason`, and the validation results |
| 5 | Three actions: **Accept** · **Edit** (change field or value) · **Reject** |
| 6 | On save, a toast: *"Learned — 'Annual Yield' will map to interest_rate_annual_pct next time"* |
| 7 | Bulk accept: "accept everything above 0.95 on this document", with the count shown before confirming |

**Endpoints:** `GET /api/review-queue`, `GET /api/documents/{id}/mappings`,
`PATCH /api/mappings/{id}`, `POST /api/mappings/bulk-accept`

**Acceptance**
- The evidence panel always shows **where**, never just the value. A review screen without
  the source is a guess with extra steps.
- `MappingPatchResponse.learned` drives the toast — that boolean **is** the feedback loop
  surfacing, and it is already in the types.
- `missing` items appear with their reason and are **not** silently filtered out.
- Keyboard: `a` accept, `r` reject, `↓` next. An analyst clearing 30 items with a mouse is
  the manual effort we claim to reduce.

**Scenario to demo:** Valley Community Bank's footnote contradicts its table. The mapper
flags it at 0.64 instead of guessing. The analyst opens it, sees both, picks the table, and
the next run knows.

---

### J5 — Prove it learned
**Covers:** feedback-driven learning + improvement rate. **Screens:** Batches (re-run) →
Insights. **This is the money shot.**

| Step | What happens |
|---|---|
| 1 | Re-run the same batch |
| 2 | Insights shows the four criteria: mapping accuracy, conversion correctness, manual effort saved, feedback improvement |
| 3 | A run table, one row per round, with the delta |
| 4 | A "learned corrections" list: field, from → to, which document, when |
| 5 | A line showing **how many fields resolved with no model call** — the precedent hits |

**Endpoints:** `GET /api/insights`, `GET /api/home/stats`

**Acceptance**
- Rounds are only comparable if documents, pack version, model, temperature and prompt
  version all match. The backend sends those; **if any differ, show "not comparable" with
  the reason instead of a number.** A fake improvement number is worse than none.
- The delta is signed and coloured, with the baseline visible beside it.
- Charts use Recharts (already a dependency), axes labelled with real units, no decoration
  that invents precision.

---

### J6 — Export the standardized dataset
**Covers:** "outputs a standardized, validated dataset". **Screen:** Dataset.

| Step | What happens |
|---|---|
| 1 | The gold table: one row per record, one column per canonical field, units in the header |
| 2 | Every cell carries its status colour, and clicking it opens the evidence panel from J4 |
| 3 | Filter by status; `missing` cells are visible, not hidden |
| 4 | Export CSV or JSON, with an **audit** toggle that includes the provenance columns |

**Endpoints:** `GET /api/batches/{id}/records?page&per_page`,
`GET /api/batches/{id}/export?format=csv|json&audit=true|false`

**Acceptance**
- Paginated — 150 `ps06` rows today, thousands later.
- The audit export includes page, bbox, rule id, confidence, model and who approved.
- Export is a **download of what the backend rendered**, not something the frontend
  assembles. Same data in, byte-identical file out, is a claim we make on stage (Law IV).

---

## 4. Screen → journey → endpoint map

| Screen | Journey | Endpoints |
|---|---|---|
| Home | all | `GET /api/home/stats` |
| Upload | J3 | `POST /api/batches` |
| Batches | J3, J5 | `GET /api/batches`, `/{id}`, `/{id}/events`, `/{id}/cancel` |
| Review | J4 | `GET /api/review-queue`, `GET /api/documents/{id}/mappings`, `PATCH /api/mappings/{id}`, `POST /api/mappings/bulk-accept` |
| Dataset | J6 | `GET /api/batches/{id}/records`, `/{id}/export` |
| Schema | J2 | `GET /api/packs`, `/{id}`, `PUT /api/packs/{id}` |
| Insights | J5 | `GET /api/insights` |
| Settings | J1 | `GET/PATCH /api/settings` |
| Health | J1 | `GET /api/health` |
| Help | — | static; put the demo script and the five laws on it |

---

## 5. States you must design, not discover

Every screen needs four, and the one everybody forgets is the third.

1. **Loading** — skeletons, not spinners, for tables you know the shape of.
2. **Empty** — "no batches yet" with the action that creates one. The first view of a tool
   shows what it does; an empty shell shows nothing.
3. **Degraded** — the model provider is down but the app still works. A banner: *"Proposals
   unavailable — 47 fields resolved from memory, 112 queued for review."* This state is a
   feature of our architecture; if it is not visible, nobody knows we have it.
4. **Error** — what went wrong and what to do, never a stack trace and never "Something
   went wrong".

---

## 6. Testing and evaluation — also yours

### 6.1 The golden set (do this first, it blocks the numbers)

**30 rows from `ps06`, hand-labelled.** For each: the source label a document would use, the
canonical field it should map to, and the correct converted value. Keep it as
`backend/eval/golden_set.csv` and treat it as frozen once agreed.

⚠ **Do not use `ps06.needs_review` as ground truth.** Measured on the file, flagged rows span
confidence 0.61–0.99 and unflagged rows span 0.60–0.99 — the flag is uncorrelated with the
score because the data is synthetic. See [`../data/samples/DATASETS.md`](../data/samples/DATASETS.md).
Our accuracy numbers come from the golden set or they are not claims.

### 6.2 End-to-end checklist (run before every demo rehearsal)

- [ ] `npm run build` clean — no TypeScript errors
- [ ] `VITE_USE_MOCK=false`, backend up, every screen loads with no console error
- [ ] Upload one of each of the six formats → all land, none kills the batch
- [ ] A corrupt file marks itself `unsupported`, batch completes
- [ ] Every value in the Dataset view has a source location when clicked
- [ ] Fix one mapping in Review → toast says learned → re-run → that field comes back `auto`
- [ ] Insights shows round 1 vs round 2 with a signed delta and the controlled variables
- [ ] Kill the backend mid-run → the UI degrades with a message, does not white-screen
- [ ] Clear the API key → Health `degraded`, run still completes into the review tray
- [ ] Export CSV with audit → page, bbox, rule id, confidence present
- [ ] Phone width (~400 px): no horizontal scroll on any screen

### 6.3 Automated

- **Vitest** for `api/client.ts` mock/live branching, status rendering, and the bbox
  normalization helper — small, fast, worth it.
- **Playwright** for J4 and J5 only: review-fix-rerun, and the insights delta. Those two
  journeys are the demo; a regression in them on the final morning is unrecoverable.
- Ali gates the **five law tests** in CI. Your job is to shout if a green CI ships a broken
  journey — that means a journey has no test.

---

## 7. Deferred, but designed in

These are not in the MVP, and the frontend should make adding them a change in one place:

| Later | Design for it now |
|---|---|
| SSE live events | one `useBatchEvents(id)` hook; polling inside it today, EventSource tomorrow — no component changes |
| Auth + multi-tenant | every API call goes through `apiFetch`; add one `Authorization` header there, never in components |
| Maker-checker | `Mapping` already distinguishes `reviewed_by` / `approved_by` in the ledger; keep the review panel's action bar data-driven so a second action can appear |
| Second domain pack | never hardcode a field name or a bank name in a component — read everything from `GET /api/packs` |
| Document viewer | keep the evidence panel behind one `<Evidence source={...}/>` component that switches on `source_location.type`; `pdfjs-dist` is already a dependency |

---

## 8. Your manual steps

1. `npm install` in `Frontend/` on your own machine.
2. Agree the golden set's 30 rows with Ihsan before labelling, so the field names match the pack.
3. Tell the group the moment you need a shape `mockData.ts` does not have — that is a
   backend contract question and it is cheaper to answer in a message than in a merge.
4. Record the fallback demo video once J1–J6 pass end to end, before the final hour.

---

## 9. Done looks like

- [ ] All six journeys pass against the live backend
- [ ] Three visual states everywhere; `missing` is visible as a result, not a filter
- [ ] Every value is clickable through to its source page or cell
- [ ] The golden set exists and the Insights numbers are computed from it
- [ ] Degraded mode is visible and tested by actually killing the model key
- [ ] A fallback video exists
