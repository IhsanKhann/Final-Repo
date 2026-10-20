# Lane: Ihsan — Engine, Agents, API, Packs

**Read [`../README.md`](../README.md) and [`../CLAUDE.md`](../CLAUDE.md) first.** This file is
the build order for the backend, in the order it must be written, with what "done" means for
each block.

You own `backend/`. Ali owns `infra/`. Tahreem owns `Frontend/`.

---

## 0. The order is not negotiable

Each block unblocks the next. Config first, because everything reads from it; contracts
second, because everything speaks them; the gate before the API, because the API has nothing
to serve without it.

| # | Block | Min | Done when |
|---|---|---|---|
| 1 | Config layer | 20 | `GET /api/health` returns live provider state with a `source` on every value |
| 2 | Contracts | 10 | A fixture round-trips Python → JSON → the frontend's own types |
| 3 | Pack loader + `banking_rates.yaml` | 15 | `GET /api/packs` feeds the Schema page |
| 4 | Adapters (5 formats) | 30 | One of each format produces `ExtractedFact`s with a `source_location` |
| 5 | Mapper (agent 2) | 25 | Two institutions' different words land on one field, with a `reason` |
| 6 | Units + validations + gate + ledger | 20 | Three lanes populated; every cell has provenance |
| 7 | FastAPI — the twelve endpoints | 30 | The React app runs with `VITE_USE_MOCK=false` |
| 8 | Feedback → precedent | 15 | Same document maps correctly the second time, **with no model call** |
| 9 | Eval: golden set, rounds 1 vs 2 | 15 | Two numbers and a delta on the Insights page |

**≈3 hours.** Extractor (agent 1) and verifier (agent 3) come after block 9 if time allows;
the pipeline is correct without them — the mapper alone satisfies the mapping requirement,
and the gate satisfies ambiguity handling.

---

## 1. Config layer — `backend/engine/config.py`

Two resolvers that deliberately differ. Full rationale in the README §6; the code shape:

```python
class Source(str, Enum):
    SESSION = "session"; DB = "db"; ENV_SEED = "env-seed"
    ENV = "env"; DEFAULT = "default"; LAST_KNOWN_GOOD = "last-known-good"; UNSET = "unset"

class Resolved(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str; value: Any; source: Source

def control(key: str) -> Resolved:      # session -> db -> env -> default
def secret_for(id: str) -> Resolved:    # session -> db -> env SEED once, then STOPS
```

- **No memo, no module singleton, no cache on either resolver.** The whole point is that the
  next call sees the new value.
- `.env` is loaded by **entry points only**, never on import of a library module. Write
  `tests/test_env_is_loaded.py` asserting every entry point calls `load_env()` — otherwise a
  valid key sits in a file nothing reads and every agent reports `NO KEY`.
- A stored `""` stops the chain. Clearing a key must be possible.
- `ConfigStore` is an interface with two implementations: `SqliteStore` (local) and
  `FirestoreStore` (cloud, Ali's). One env var picks it.

**Providers** — `backend/intelligence/providers.py`. Four rows, two dialects, **no network
call in the module**, so both dialects are testable with no key and no wifi:

```python
PROVIDERS = {
  "openai":     Provider(base_url="https://api.openai.com/v1",      dialect=OPENAI,    models_need_key=True),
  "openrouter": Provider(base_url="https://openrouter.ai/api/v1",   dialect=OPENAI,    models_need_key=False),
  "google":     Provider(base_url=".../openai",                     dialect=OPENAI,    models_need_key=True),
  "anthropic":  Provider(base_url="https://api.anthropic.com/v1",   dialect=ANTHROPIC, models_need_key=True),
}
```

Every failure maps to a named state — `no-key`, `bad-key`, `model-unavailable`,
`rate-limited`, `timeout`, `provider-down`. **A listed model is not a callable one:** a
provider's `/models` will return models that 404 for keys issued after a cutoff, so
`model-unavailable` is its own state and every default model is one you have actually called.

---

## 2. Contracts — `backend/engine/contracts.py`

Pydantic v2 mirrors of `Frontend/src/api/types.ts`, `extra="forbid"` on everything crossing a
boundary. The vocabulary is theirs: `auto|review|missing|approved|rejected`, bbox normalized
0–1 `[x,y,w,h]`, confidence 0–1, `Conversion{factor, rule_id, formula_text}`.

The invariant that must live in the model, not in a comment:

```python
@model_validator(mode="after")
def _provenance_required(self):
    if self.status in ("auto", "approved") and self.source_location is None:
        raise ValueError("a value without provenance cannot be constructed")
    return self
```

Four internal types the frontend never sees: `DocumentRecord`, `ExtractedFact`, `Proposal`,
`FeedbackEvent`.

---

## 3. Pack loader — `backend/engine/packs.py` + `backend/packs/banking_rates.yaml`

A pack is **data**: no code, no prompts, no model config. Five declaration groups: `fields`
(name, type, unit, synonyms, range), `conversions` (from, to, factor, formula_text),
`precedence`, `materiality`, `ambiguity`. Every declaration carries `provenance:
QUOTED|AUTHORED|MEASURED` with its mandatory fields.

The loader validates provenance and **fails the whole run before any document is read** if a
declaration is malformed — naming the file and the line. `tests/test_packs.py` opens every
cited file and checks the quote is really there, on the page named.

Author `banking_rates.yaml` from the `ps06` columns: `rate_pct` → `interest_rate_annual_pct`,
`apy_pct` → `annual_percentage_yield_pct`, `min_deposit` → `minimum_deposit_usd`,
`term_months` → `term_months` (0 = no term, a demand product — not a missing value),
`effective_date` → `effective_date`. Include the `percent_per_month → percent_per_annum ×12`
conversion; Pacific Savings' generated sheet is what exercises it.

---

## 4. Adapters — `backend/adapters/`

One module per format, no shared state, each returning `ExtractedFact[]`.

| Module | Library | Source location it emits |
|---|---|---|
| `sheet.py` | pandas + openpyxl | `{type:'sheet', sheet, cell}` |
| `csv.py` | pandas | `{type:'sheet', sheet:'csv', cell}` |
| `html.py` | selectolax | `{type:'text', start, end}` |
| `pdf_text.py` | pdfplumber | `{type:'pdf', page, bbox}` — **divide by page width/height here**, once |
| `pdf_scan.py` | PyMuPDF rasterize → GPT-4o vision | `{type:'pdf', page, bbox}` |

`pdf_scan.py` uses PyMuPDF because it has **no system dependencies on Windows** — poppler
would cost you the hour. Document AI swaps in behind the same function signature when Ali's
processor id lands in the config store.

A corrupt file marks **that document** `unsupported` with the parser error and the batch
continues. One bad file must never kill a run.

**Also write `backend/eval/make_documents.py`** — generates the six source documents from
`ps06` rows, one institution per format with different terminology each. Deterministic: same
CSV in, byte-identical documents out. Without it there is nothing to ingest, because
`ps06.csv` is already-extracted tabular data, not documents. See
[`../data/samples/DATASETS.md`](../data/samples/DATASETS.md) §1.

---

## 5. Mapper — `backend/intelligence/mapper.py`

```
retrieve candidates   (deterministic: exact synonym → precedent → fuzzy ratio)
   ↓ exactly one strong candidate?  → resolve with NO model call
   ↓ otherwise
ask the model to choose FROM THE CANDIDATE LIST, with a reason
   ↓
Proposal{field, confidence, reason}  →  engine/resolve.py decides
```

**The model may not name a field the pack does not declare** — constrain the choice to the
retrieved list and reject anything else as `missing`. Temperature 0, structured output with
an enforced schema, token budget, hard timeout, backoff on 429. A non-conforming reply is one
retry, then `Unavailable` — which means the review tray, never a guess.

`intelligence/base.py` returns `Proposal | Unavailable` and **never raises across the seam**.
That single decision is what makes a provider outage a degraded banner instead of a failed run.

---

## 6. Backbone — `units.py`, `resolve.py`, `gate.py`, `ledger.py`

- `units.py` — table driven entirely by pack `conversions`. Produce `formula_text` for the
  UI (`"× 12 (monthly → annual)"`). A conversion moving a value more than three orders of
  magnitude goes to review regardless of confidence.
- `resolve.py` — pure function: `(Proposal | None, pack, precedents) → Mapping`. Authority
  order `PACK_QUOTED > PACK_AUTHORED > ANALYST > MODEL`.
- `gate.py` — three lanes, defaults **0.90 / 0.60**. ⚠ These start as *stated defaults*, not
  calibrated values: `ps06.needs_review` is uncorrelated with `extraction_confidence` and
  cannot calibrate anything. Fit them against the golden set, or say on stage that they are
  defaults. Do not claim calibration we did not do.
- `ledger.py` — one evidence record per cell, **append only**. Re-runs add a version.
- Validations from the pack: type, range, plus cross-field (`apy_pct >= rate_pct` holds in
  all 150 `ps06` rows — a free, real validation rule).

---

## 7. API — `backend/api/`

The twelve endpoints in README §4, thin by rule: parse, call the engine, serialize. No logic
in a route handler. SQLite stands in for GCS/BigQuery behind a `Repository` interface.

`/api/batches/{id}/events` is SSE in the contract; **MVP returns a JSON array and Tahreem
polls**. Keep the event shape identical so the swap is one function.

---

## 8. Feedback — `backend/memory/`

`PATCH /api/mappings/{id}` writes a `FeedbackEvent` **and** a precedent
`(tenant, source_label) → canonical_field`, tagged `ANALYST`, and returns
`learned: true` with a `learned_message` the UI toasts. The next run's retrieval returns
precedents first and resolves them **with no model call at all** — faster, cheaper, and
provably identical to what the analyst chose.

Count `precedents_applied` and `model_calls_skipped`. They are the two numbers that prove
the loop is real rather than a re-prompt.

---

## 9. Eval — `backend/eval/`

`golden_set.csv` (30 hand-labelled rows, agreed with Tahreem), a scorer, and
`RoundReport{round, pack, model, temperature, prompt_version, docs, fields, auto_accepted,
flagged, missing, mapping_accuracy, conversion_correctness, precedents_applied,
model_calls_skipped, analyst_minutes_saved, cost_usd, delta_vs_previous}`.

**Comparability check is part of the report, not a nicety:** if documents, pack version,
model, temperature or prompt version differ between rounds, the report says *not comparable*
and the UI shows that instead of a number.

---

## 10. Deferred — and the seam that makes each one a drop-in

Nothing below is in the MVP, and **every one of them is a swap behind an interface that
exists on day one.** That is why deferring is safe. Write the interface even where there is
only one implementation.

| Deferred | Seam that must exist from the first hour | What adding it later costs |
|---|---|---|
| BigQuery / GCS storage | `Repository` interface; `SqliteRepository` today | a second class, one env var |
| Firestore config store | `ConfigStore` interface; `SqliteStore` today | Ali's class, one env var |
| Document AI | `pdf_scan.py` function signature `(bytes, mime) -> ExtractedFact[]` | one module body |
| >15-page async batch | the router already branches on page count; the long branch raises `NotImplemented` today | one branch |
| Eventarc / Pub/Sub fan-out | the pipeline entry point takes **one document**, never a list | Ali's job wrapper, no engine change |
| SSE events | events already written to an `EventLog`; the endpoint serializes it | one endpoint |
| Auth / multi-tenant | `tenant_id` is a column and a parameter **everywhere now**, defaulted to `"demo"` | a middleware that sets it |
| Maker-checker | ledger already has `reviewed_by` **and** `approved_by` | a gate rule reading pack materiality |
| Round 3 promotion | precedents already counted per `(source_label, field)` | a query and a `PROPOSED` pack entry |
| Second domain pack | Law II test keeps the engine clean | writing a YAML file |
| Vertex / Gemini | provider row + dialect already exist | a config change, no code |

**The rule:** if deferring something would later require changing a function signature in
more than one file, the seam is wrong — fix the seam now, not the feature.

---

## 11. What you must do manually

1. **Put `OPENAI_API_KEY` in `.env`** (seed only — the config store takes ownership on first
   run). Confirm `.env` is gitignored before the first commit.
2. **Author `packs/banking_rates.yaml` yourself**, including the `because` on every
   `AUTHORED` line. A model may draft it; a human accepts it. That is the product's claim and
   it has to be true of our own pack.
3. **Agree the golden set's 30 rows with Tahreem** so her labels and your field names match.
4. **Decide the two gate thresholds and say how you got them.** Defaults are fine; a false
   calibration claim is not.
5. **Get the Doc AI processor id and bucket names from Ali** and put them in the config store,
   not in `.env`.
6. **Run the demo end to end twice yourself** before rehearsing with the team. The second run
   is where the precedent proves itself, and it is the step most likely to be skipped.
7. **Merge discipline:** rebase on `main` before pushing; never resolve a conflict in
   `Frontend/` or `infra/` yourself.

---

## 12. Done looks like

- [ ] `pytest backend/tests -q` green, five law tests included
- [ ] Frontend runs with `VITE_USE_MOCK=false`, every screen populated
- [ ] One document of each format in → mapped rows out with provenance
- [ ] One flagged field fixed → re-run resolves it with `model_calls_skipped > 0`
- [ ] Round 1 and round 2 reports exist with the controlled variables recorded
- [ ] `grep -ri "APY\|money market\|<bank name>" backend/engine backend/adapters backend/api` → nothing
- [ ] No key or `.env` in `git log -p`
