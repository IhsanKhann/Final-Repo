# Canon — PS-12 judge guide

**Cross-Source Data Standardization & Transformation Agent**
National AI Hackathon '26 · Team: Ihsan, Ali, Tahreem

| | |
|---|---|
| **Live backend** | https://canon-backend-1057093770172.us-central1.run.app |
| **Health (start here)** | https://canon-backend-1057093770172.us-central1.run.app/api/health |
| **Repository** | https://github.com/IhsanKhann/Final-Repo |
| **GCP project** | `ps12-canon-hackathon26` · Cloud Run revision `canon-backend-00003-w8t` · `us-central1` |
| **Frontend** | run locally (below) — the backend is the deployed artifact |

---

## 1. What this is, in one paragraph

Documents arrive from unlike sources in unlike formats. Canon extracts reportable fields,
maps each one onto a field the **customer** declared in a YAML domain pack, converts units
using factors the **customer** declared, flags anything uncertain for a human instead of
guessing, and learns from every correction so the next run is measurably better. Every
value in the output carries the page, cell or character offset it came from.

The design split that makes it defensible: **the model proposes, a deterministic backbone
decides.** No model call occurs anywhere inside `backend/engine/`, and a test fails the
build if one appears.

---

## 2. Run the acceptance test yourself — one command, 18 checks

```bash
# against the deployed service
PYTHONPATH=. python backend/eval/acceptance.py https://canon-backend-1057093770172.us-central1.run.app

# or locally
PYTHONPATH=. python backend/eval/acceptance.py http://localhost:8000
```

Measured 2026-10-20 against the deployed service — **17 of 18 pass, and the 18th is an
expected refusal**:

```
[PASS] service answers /api/health                        22.6s cold start, min-instances=0
[PASS] pack is loaded and accepted                        banking_rates v1.0.0 (accepted), 5 fields
[PASS] golden set is confirmed                            30/30 rows
[PASS] a provider key resolves from the store             source=db  (not from the image)
[PASS] all six source documents exist                     6/6
[PASS] batch accepted                                     201 CREATED
[PASS] every file processed                               stage=ready
[----] one unreadable file does not kill the batch        5 done, 1 honestly refused:
                                                          metro_credit_union_rates_scan.pdf
                                                          "rasterized and not read (model-unavailable)"
[PASS] three lanes populated                              464 fields: 278 auto / 141 review / 45 missing
[PASS] dataset holds many records per document            126 records from 6 documents
[PASS] every value carries a source location              90/90
[PASS] unit conversion is explained in words              0.1157 -> 1.3884  (x 12 monthly -> annual)
[PASS] review queue is populated                          186 items
[PASS] an analyst can assign the field                    target_field accepted
[PASS] the correction is learned                          "the next run resolves it with no model call"
[PASS] insights shows the correction                      1 correction
[PASS] effort saved is counted                            418.5 analyst minutes
[PASS] audit export produces CSV                          with page, rule, confidence columns
```

`pytest backend/tests -q` runs the unit suite, including the five laws below.

---

## 3. Run the frontend

```bash
cd Frontend && npm install && npm run dev     # http://localhost:5173
```

`Frontend/.env` already points at `http://localhost:8000`. Change it to the Cloud Run URL
to drive the deployed backend. **There is no mock mode** — the mock data path was deleted,
not switched off, because a flag that can be flipped back is a way to show fabricated
numbers by accident.

Backend locally:

```bash
pip install -r backend/requirements.txt
python -m uvicorn backend.api.main:app --port 8000
```

No API key is needed to start. With no key the pipeline still runs: everything with a
precedent resolves deterministically, the rest goes to the review tray, and Health says
`degraded` with the reason.

---

## 4. The five-minute demo

1. **Schema page.** "This is the customer's rulebook. Every rule carries `QUOTED` with a
   document and page, `AUTHORED` with the reasoning, or `MEASURED` with a count. We did not
   write it and the engine has never heard of a bank."
2. **Upload** the six files in `backend/eval/generated/` — a text PDF, a scanned PDF, an
   HTML page, a spreadsheet, a narrative disclosure, and a PDF whose footnote contradicts
   its own table.
3. **Dataset.** One schema, six sources, units aligned, **126 records** — because one
   spreadsheet holds thirty, not one.
4. **Click any cell.** Page and bounding box, or sheet cell, or character offsets. The rule
   that fired. The pack version. The confidence.
   Show the conversion: Pacific Savings publishes a **monthly** rate; `0.1157 × 12 = 1.3884`,
   and the factor is declared in the customer's pack, not inferred by us.
5. **Review tray.** Fix one flagged field. The toast reads *"Learned: … The next run
   resolves it with no model call."*
6. **Re-run.** Auto-accept rose from 278 to 337 and the review queue fell from 139 to 82,
   because the precedent applied. **That is the feedback loop, measured, not asserted.**
7. **Insights.** The correction, and 418.5 analyst minutes saved.

---

## 5. The dataset we were told to use, and what we found in it

We were told to reuse `ps01_documents_metadata.csv` or `ps06_sample_rate_sheets.csv`. We
used `ps06` as the primary. Two measured facts changed how we built, and we state both:

**`ps06.needs_review` is uncorrelated with `extraction_confidence`.** Flagged rows span
0.61–0.99 and unflagged rows span 0.60–0.99 — the same range. The flag is effectively
random with respect to the score, because the file is synthetic. **So we did not calibrate
our thresholds against it and we do not claim we did.** `0.90 / 0.60` are stated defaults.
Accuracy is measured against a hand-labelled golden set instead.

**Neither file contains actual documents.** Both are already-extracted tables. On their own
they cannot demonstrate "multi-format ingestion", which is the first technical requirement.
So we *generate* the source documents from `ps06`'s own rows — one institution per format,
each using different terminology for the same quantities:

| Institution | Format | Says | Tests |
|---|---|---|---|
| First National Bank | text PDF | `Rate`, `APY` | the control |
| Metro Credit Union | scanned PDF | `Interest`, `Opening Balance` | OCR + an undeclared synonym |
| Heritage Financial | HTML | `p.a. %`, `effective yield` | lowercase, `1.36 %` with a space |
| **Pacific Savings** | XLSX | **`Nominal (monthly)`** | **the ×12 unit conversion** |
| Summit Trust | narrative prose | *"pays 3.416% annually"* | no table at all |
| **Valley Community** | text PDF | `Rate*` + footnote | **a footnote contradicting the table** |

`backend/eval/make_documents.py` is deterministic — same CSV in, byte-identical documents
out — so the demo cannot drift. This is not faking the problem; it is reconstructing the
exact problem the statement describes: *"different companies report equivalent information
using different layouts, terminology, units of measurement, table structures, narrative
formats, footnotes."*

---

## 6. The five technical requirements, and our evidence

| Requirement | Status | Evidence |
|---|---|---|
| **Multi-format ingestion** — PDFs (text and scanned), HTML, spreadsheets, narrative | **4½ / 5** | CSV, XLSX, HTML, text PDF and narrative all ingest with provenance. Narrative yields 155 figures across 31 records from prose with no headings. **Scanned PDFs rasterize and are honestly refused** — see §8. |
| **Intelligent field mapping** | **done** | `Nominal (monthly)`, `p.a. %` and `Rate` all resolve to `interest_rate_annual_pct`. A live GPT-4o call mapped the undeclared `Opening Balance` → `minimum_deposit_usd`. The model may only choose from fields the pack declares. |
| **Unit conversion + configurable business rules** | **done** | `0.1157 × 12 = 1.3884`, factor declared in the pack with `formula_text` for the UI. Zero model involvement. **conversion_correctness = 1.0 measured.** Edit the YAML, re-run, the column changes. |
| **Ambiguity handling** | **done** | Three lanes: 278 auto / 141 review / 45 missing. A value without provenance cannot be constructed — the schema refuses. A model that names an undeclared field lands in `missing` with the reason. An unavailable model routes to `review`, never to a guess. |
| **Feedback-driven learning** | **done** | A correction writes a precedent; the next run resolves it with **no model call**. Measured across two runs: auto 278 → 337, review 139 → 82. |

### Evaluation criteria

| Criterion | Our number |
|---|---|
| Field mapping accuracy | **17 of 30 confirmed golden rows matched**; see §8 for the 13 |
| Unit conversion correctness | **1.0** |
| Reduction in manual standardization effort | **418.5 analyst minutes** on one batch, counted by the pipeline |
| Improvement from feedback | **auto 278 → 337, review 139 → 82** after one correction |

---

## 7. Where the agentic AI is, precisely

Three agent roles are designed; **one is built and running**: the **mapper**. It receives a
fact plus candidates retrieved deterministically from the pack's synonyms and the tenant's
precedents, chooses among them, and writes its reason. It cannot name a field the pack does
not declare.

Everything else is deterministic **on purpose**: ingestion, unit conversion, the gate, the
feedback write-back and the export. Unit-conversion correctness is a scored criterion; a
lookup table scores 1.0 and a model scores 0.97 inexplicably.

Model settings: pinned model, structured output, per-document token budget, hard timeout,
exponential backoff. `temperature=0` on the OpenAI dialect; **omitted on the Anthropic
dialect**, because current Claude models removed the parameter and any value returns 400.
The round report records the sampling that was *sent*, never what was intended.

**Providers are four rows and two wire dialects** — OpenAI, OpenRouter (bring-your-own
model), Google/Vertex, Anthropic — and the provider module makes no network call, so both
dialects are testable with no key and no connectivity.

---

## 8. What we do NOT claim

Stated plainly, because each of these is something a careful judge will probe.

1. **We have never read a scanned PDF.** The path rasterizes the page and reports
   `model-unavailable`, which routes the document to human review. No vision call has ever
   succeeded. The honest line is *"it rasterizes and routes to a human"*, not *"we read the scan."*
2. **One agent, not three.** Extractor and verifier are designed and unbuilt.
3. **No LangGraph.** Orchestration is a deterministic Python pipeline. We think that is the
   stronger claim, but it is not a state-machine framework.
4. **Page quotas are not enforced.** The tiering in the business model is a plan, not code.
5. **Terraform was written but never applied.** `infra/` is correct infrastructure-as-code;
   the live resources were provisioned with `gcloud` and Cloud Build.
6. **Mapping accuracy is 17 of 30, not 46.7%.** The raw figure divides by rows that cannot
   match: 5 scanned-PDF rows (no vision call), 5 narrative rows whose golden "labels" are
   prose fragments and cannot join on a heading, and 3 header-text drifts between the two
   generators. We report the matched count and the breakdown rather than the ratio.

---

## 9. The five laws, each enforced by a test

| # | Law | Test |
|---|---|---|
| I | No model call inside `engine/` | `test_no_model_call_in_engine.py` |
| II | No domain noun outside `packs/` | `test_engine_is_domain_agnostic.py` — with a **positive control**, so a broken scanner cannot read as a clean engine |
| III | Nothing invented: every pack rule is `QUOTED` / `AUTHORED` / `MEASURED`, and acceptance names a human | `test_packs.py` opens the cited file and checks the quote |
| IV | The export is a render, not a generation — byte-identical | `test_render_is_byte_identical.py` |
| V | Three states, never two | `engine/gate.py` |

Law III refused our own pack three times while we were accepting it — declarations marked
accepted with nobody named, and an unquoted YAML date. That is the guard working on us.

---

## 10. How the analyst is facilitated

- **Worst-first review queue**, each row carrying its source label, its record, the reason,
  and the confidence.
- **Side-by-side evidence**: the document on the left with the exact page, cell or span;
  the proposal on the right with the rule that fired.
- **Three actions** — accept, edit, reject — and the analyst may **reassign the field**, not
  merely rate our guess. That correction is the most valuable one and it is what teaches.
- **Immediate feedback**: *"Learned: 'Opening Balance' means minimum_deposit_usd. The next
  run resolves it with no model call."*
- **Bulk accept** above a confidence the analyst chooses.
- **Settings page** changes provider, model, thresholds and keys **live, with no redeploy**,
  and shows where every value resolved from (`db`, `env-seed`, `default`, `unset`).
- **Honest empty and degraded states**: when no run has scored, the number is absent and the
  Health page says why, rather than showing a zero that looks like failure.

---

## 11. Operational proof: credentials survive a redeploy

The config layer is the reason this is a product rather than a script:

```
revision 00001  → PATCH /api/settings with a key → "key present | source=db"
deploy   00002  → "key present | source=db"   ← survived
deploy   00003  → "key present | source=db"   ← survived again

container env vars: CONFIG_STORE, GCP_PROJECT_ID, GCP_REGION, DOCAI_LOCATION
                    → NO CREDENTIAL
```

Two resolvers, deliberately different: a **control** chains `session → db → env → default`;
a **secret** chains `session → db → env SEED once`, then stops. Env is a seed, never a
fallback, because otherwise the key you paste dies, the stale one answers, and the screen
still says connected.

When a second domain pack was added, the deployed Pack layer went **down** — *"two packs
present and no active pack configured"* — rather than silently picking one. Fixed by writing
`active_pack_id` to the config store over the API, **with no redeploy.**
