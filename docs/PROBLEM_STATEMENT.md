# PS-12 — the problem statement, verbatim, and what we cover

Moved out of `README.md` so the README stays short enough for a panel to read. Nothing here is paraphrased; the statement is as issued.

---

## The statement, as issued

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

---

## Coverage, requirement by requirement

| Requirement | MVP | What is real | What is left |
|---|---|---|---|
| **Multi-format ingestion** | 85% | CSV/XLSX (pandas, openpyxl), text PDF (pdfplumber, page + bbox), HTML (selectolax), narrative disclosures (`adapters/narrative.py` — deterministic, not an agent). **Scanned PDF: `pdf_scan.py` is written and tested, but nothing routes to it** — both PDF adapters claim `application/pdf` and only `pdf_text` is in the `ADAPTERS` table | Wire the scan route; a real vision backend; Document AI swap-in; >15-page async batch route |
| **Intelligent field mapping** | 90% | Deterministic candidate retrieval over pack synonyms + precedents, LLM arbitration only where no candidate wins, reason on every mapping, constrained to declared fields | Embedding retrieval for unlisted terms; 2nd domain pack |
| **Unit conversion + business rules** | 100% | Table-driven converter whose factors are declared in the pack, with `formula_text`. Edit pack → re-run → column changes | — |
| **Ambiguity handling** | 100% | Three lanes on **stated defaults** (0.90 / 0.60) — not calibrated, and we say so on stage; `missing` shown, never silently dropped; no value constructible without provenance | Calibration, which needs the golden set confirmed; maker-checker on high-materiality fields |
| **Feedback-driven learning** | 80% | The mechanism: a correction writes a precedent, a re-run applies it with **no model call**, and the round report carries the delta and the six controlled variables. Covered by tests | Running it — **no round has been run yet, so the improvement figure is unmeasured**; round 3 promotion into a proposed pack v2 |

**≈90% of the technical requirements; all four evaluation criteria measurable.**
**Measurable, not measured.** Two numbers do not yet exist and we do not quote them:
**0 of 30 golden-set rows are confirmed, so there is no accuracy figure anywhere in this
repo**, and no round has been run, so there is no improvement rate either. The scorer
refuses to print accuracy below 30 confirmed rows precisely so that this gap cannot be
papered over by accident (`docs/AGREEMENTS.md` §6). The remaining gap is
confirmation-and-execution-shaped; it is no longer deployment-shaped — the backend is
live (§7).

### Deferred on purpose — and the seam that makes each one a drop-in

Nothing is cut without a seam. **Every deferred item is a swap behind an interface that
exists from the first hour**, which is the only thing that makes deferring safe. Write the
interface even where there is one implementation.

| Deferred | Seam that exists from day one | Cost to add later |
|---|---|---|
| BigQuery / GCS storage | `Repository` interface; `SqliteRepository` today | a second class, one env var |
| ~~Firestore config store~~ | **no longer deferred.** `engine/firestore_store.py` exists behind the same `ConfigStore` interface; `CONFIG_STORE=firestore` is what the deployed revision runs | done — it cost exactly the one class and the one env var |
| **Extractor agent** | `intelligence/base.py` returns `Proposal \| Unavailable`, never raises; the mapper is already one caller of it | a second caller of an existing contract |
| **Verifier agent** | same contract, plus `gate.py` already reads `verifier_rejected` and drops rather than downgrades the field | a third caller, no gate change |
| Checkpoint / resume orchestration | `pipeline.py` is one function over plain data, so state is already explicit at the seam | a store for node state, and the edges re-expressed over it |
| A real vision backend for scans | `pdf_scan.py` takes `vision: VisionFn` and its default returns `Unavailable` — it never guesses and never half-reads a document | one injected function |
| Document AI | `pdf_scan.py` signature `(bytes, mime) -> ExtractedFact[]`, the same seam | one module body |
| >15-page async batch | **no seam yet.** `async_page_threshold` (default 15) is declared in `engine/config.py` and has exactly one occurrence in the repo: its own declaration. `page_count` is on every `AdapterResult` and both PDF adapters populate it | the branch itself, plus a caller for the control |
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

Judges will ask, and the honest answer is more specific than "three agents". Three agents
are **designed**. **One is built.** The distinction is the answer, not a caveat on it:

| Agent | State | Input | Output | Why it must be an agent |
|---|---|---|---|---|
| **Mapper** | **BUILT** — `intelligence/mapper.py`, called from `pipeline.py` | a fact + retrieved candidates from pack & memory | chosen field + `reason` + confidence | recognising *unlisted* terminology is the judgement the problem statement is about |
| **Extractor** | **DESIGNED** — no `intelligence/extractor.py` exists | hard pages — scans, narrative, broken tables, footnotes | `ExtractedFact[]` with page + bbox | layout genuinely defeats parsers |
| **Verifier** | **DESIGNED** — no `intelligence/verifier.py` exists | resolved value + its source snippet | supported / not, + reason | catches the mapper; its rejections are shown, not hidden |

The reasoning for all three still holds, and **the seam for the other two is already
open.** `intelligence/base.py` returns `Proposal | Unavailable` and never raises; the
mapper is simply its first caller. Adding the extractor or the verifier is a new caller of
a contract that exists, not a new contract — and for the verifier the decision side is
wired too: `engine/gate.py` already reads `verifier_rejected` and **drops** the field
rather than downgrading it, with a test that holds it to that. `resolve.py` passes
`verifier_rejected=False` today because nothing sets it yet.

#### The orchestration is `pipeline.py`, and that is the claim — not a retreat from one

**There is no LangGraph in this repo.** The string appears in exactly one place: the list
of banned imports in `tests/test_no_model_call_in_engine.py`. What runs instead is
`backend/pipeline.py` — a 258-line deterministic composition root whose
`process_document()` takes **one document** and whose only job is wiring, because every
decision belongs in `engine/resolve.py`.

That determinism is the differentiator, not a shortfall. Unit-conversion correctness and
field-mapping accuracy are *scored* criteria, and a run we cannot reproduce cannot be
scored. An orchestrator that picks its own route takes a different path on stage than it
took in rehearsal; this one takes the same path every time, and the five laws are
enforceable precisely because the route is ours.

**What that costs, stated plainly:** there is **no checkpointing and no resume.** A
document that fails halfway restarts from the beginning. Retry and exponential backoff
**do** exist, but one layer down in `intelligence/base.py`, where they cover the model
call — 429 backoff, one retry for a non-conforming reply, then `Unavailable`. They do not
cover the pipeline. Fan-out is the seam that *is* real: one document per call means
Eventarc, Pub/Sub or a Cloud Run job per file becomes a wrapper around this function
rather than a change to it.

---
