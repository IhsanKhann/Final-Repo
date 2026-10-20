# Datasets — PS-12 only

Two files, both supplied by the hackathon for **PS-12, Cross-Source Data Standardization &
Transformation Agent**. They are synthetic samples for prototyping, not production data.
Nothing else from the original sample archive is in this repo; the other problem
statements' datasets have been removed.

| File | Rows | What it is | Our use |
|---|---|---|---|
| [`ps06_sample_rate_sheets.csv`](ps06_sample_rate_sheets.csv) | 150 | Deposit-rate records already extracted from bank rate sheets, with a confidence score per record | **Primary.** The field-mapping and unit-conversion target, and the source material for our generated documents |
| [`ps01_documents_metadata.csv`](ps01_documents_metadata.csv) | 200 | Document-inventory metadata — filenames, source channels, sizes, OCR snippets | **Secondary.** Realistic ingestion variety: the mix of document kinds and arrival channels we must claim to handle |

---

## 1. `ps06_sample_rate_sheets.csv` — 150 records

```
source_file,institution_name,product_type,term_months,rate_pct,apy_pct,
min_deposit,effective_date,extraction_confidence,needs_review
```

| Column | Type | Range in this file |
|---|---|---|
| `source_file` | string | `first_national_bank_rates_page1.pdf` — **carries a page number**, which is where our provenance story starts |
| `institution_name` | string | 6 values: First National Bank, Heritage Financial, Metro Credit Union, Pacific Savings, Summit Trust, Valley Community Bank |
| `product_type` | string | 6 values: High-Yield Savings (29), Savings (28), Checking Plus (26), Money Market (23), IRA CD (23), CD (21) |
| `term_months` | int | 0, 3, 6, 12, 24, 36, 60 — **0 means "no term"**, i.e. a demand product, not a missing value |
| `rate_pct` | float | nominal rate, percent per annum |
| `apy_pct` | float | annual percentage yield — **always ≥ `rate_pct`**, which is a cross-field validation we can assert |
| `min_deposit` | int | 0 – 500+, USD |
| `effective_date` | date | only 3 values: 2026-07-01, 2026-08-01, 2026-09-01 |
| `extraction_confidence` | float | 0.60 – 0.99, mean 0.807 |
| `needs_review` | bool | 33 True (22%), 117 False |

### ⚠ Two things about this file that will cost you an hour if you assume otherwise

**1. `needs_review` is NOT correlated with `extraction_confidence`.** Measured on the file:

```
needs_review = True    confidence 0.61 – 0.99   n = 33
needs_review = False   confidence 0.60 – 0.99   n = 117
```

The ranges are identical. The flag is effectively random with respect to the score, because
the file is synthetic. **So you cannot calibrate the gate thresholds against these labels,
and you must not claim on stage that we did.** What the column is still good for:

- the **22% flag rate** is a reasonable reference point for "what fraction of fields a real
  pipeline sends to review" — quote it as context, never as a label we learned from;
- both columns are **inputs our pipeline must handle gracefully** — a prior arriving from an
  upstream extractor, which we record as evidence and may override, exactly as we would an
  analyst's prior.

To calibrate the thresholds honestly, hand-label a **golden set of 30 rows** (the field each
source label should map to, and the correct converted value) and fit against that. That
golden set is also what the round reports score against. It is 20 minutes of work and it is
the difference between a measured claim and a story.

**2. There are no actual documents in this file.** It is already-extracted, already-tabular
data. On its own it cannot demonstrate "multi-format ingestion: PDFs (text and scanned),
HTML pages, spreadsheets, and narrative disclosures" — the first technical requirement.

**What we do about it:** generate our source documents *from* these rows, one institution
per format, each using **different terminology and layout for the same quantities**. That is
not faking the problem; it is reconstructing exactly the problem the statement describes —
"different companies report equivalent information using different layouts, terminology,
units of measurement, table structures, narrative formats, footnotes".

```
First National Bank    → text PDF,  table, columns headed "Rate" / "APY" / "Min. Deposit"
Metro Credit Union     → scanned PDF (rasterized), headed "Interest" / "Annual Yield"
Heritage Financial     → HTML page, headed "p.a. %" / "effective yield", values as "1.36 %"
Pacific Savings        → XLSX,      headed "Nominal (monthly)" — **monthly rate, needs ×12**
Summit Trust           → narrative paragraph: "...pays 4.06% annually on balances over $500..."
Valley Community Bank  → text PDF with a footnote that contradicts the table (the ambiguity case)
```

The generator lives in `backend/eval/make_documents.py` and is deterministic — same CSV in,
byte-identical documents out, so the demo cannot drift. Pacific Savings' monthly quote is
what proves the unit converter; Valley Community's footnote is what proves the review lane.

---

## 2. `ps01_documents_metadata.csv` — 200 records

```
doc_id,filename,source,received_date,file_type,file_size_kb,
ocr_text_snippet,current_status,assigned_stream
```

| Column | What is actually in it |
|---|---|
| `file_type` | **`PDF` for all 200 rows** — there is no format variety here despite the name |
| `source` | Manual Upload 49 · API Feed 44 · Email Ingestion 41 · Web Scraper 33 · FTP Upload 33 |
| `filename` | 10 document kinds: regulatory_filing 27, investor_presentation 25, annual_report 21, technical_report 21, **esg_disclosure 20**, internal_memo 19, news_article 18, press_release 17, earnings_call_transcript 16, quarterly_report 16 |
| `file_size_kb` | 59 – 4,943 |
| `ocr_text_snippet` | templated synthetic text, e.g. *"Sample OCR text for annual report document #1. Contains references to Q3 financials and market data."* — **no real field values in it** |
| `current_status` | `Pending` for all 200 rows — no signal |
| `assigned_stream` | Financial Analysis 46 · Regulatory Compliance 44 · Discard 42 · Archive 35 · Market Research 33 — this is **PS-01's** routing label, not ours |

### How we use it

- **Ingestion variety, as a claim we can back.** Five arrival channels and ten document
  kinds is the "hundreds of external sources" shape. Our upload screen and batch model
  mirror those channels.
- **Size distribution for the routing rule.** Documents up to ~5 MB, which is where the
  ">15 pages routes to async batch processing" decision belongs.
- **`esg_disclosure` (20 rows) is the second domain pack.** It is the cheapest proof that
  the engine is domain-agnostic: a second pack, same engine, zero code change.

### What it is not

Not ground truth for mapping, not a source of field values, and not a format mix.
`current_status` and `assigned_stream` belong to a different problem statement — **ignore
them**, and do not let them leak into the engine as domain nouns (Law II).

---

## 3. What each evaluation criterion is measured against

| Criterion | Measured against |
|---|---|
| Field mapping accuracy | the hand-labelled **golden set of 30 `ps06` rows** |
| Unit conversion correctness | the generated documents, where the correct converted value is known by construction (Pacific Savings' ×12 is the hard case) |
| Reduction in manual standardization effort | fields auto-accepted × minutes per field × analyst rate, counted by the pipeline |
| Improvement rate from feedback loop | round 1 vs round 2 vs round 3 reports on the **same** documents, pack, model, temperature and prompt version |

---

## 4. Provenance of these files

From the hackathon's `sample.zip`, unmodified. The archive's own note: *"Each folder
contains synthetic/sample data for the corresponding problem statement. These are NOT real
production datasets — they are representative samples for prototyping."* Only the two
PS-12 files were copied into this repo.
