# Agreements — decided, not up for re-litigation

Decisions that must be identical across three people's machines. Each one is here because
getting it wrong is **silent** — the thing appears to work and fails later, or fails with
an error that names the wrong cause.

Change one only by saying so in the group chat and editing this file in the same commit.

---

## 1. GCP project

| | |
|---|---|
| **Project ID** | `ps12-canon-hackathon26` |
| **Project number** | `1057093770172` |
| **Created** | 2026-10-20, by `mortalihsan@gmail.com` |
| **Owner** | Ihsan |
| **Second owner** | Ali — `muhammadalisajjadakhunzada@gmail.com` *(note the spelling: **akhunzada**, no `d` before the `z`, as Google has it)* |

⚠ **Billing is NOT enabled, and no open billing account exists on any of our three logins.**
Measured 2026-10-20:

```
mortalihsan@gmail.com      013BD8-152A32-8F6EDE  My Billing Account                           OPEN: False
ali (akhunzada)            0133E2-1F0A79-FC17C9  Google Cloud Platform Trial Billing Account  OPEN: False
ali (akhunzada)            01BBC4-509D95-E840B0  My Billing Account                           OPEN: False
sahreenkm@gmail.com        015092-82619C-C1B37E  My Billing Account                           OPEN: False
```

Until one is open and linked, **nothing cloud-side can run**: no Document AI, no Cloud Run
deploy, no Eventarc, no BigQuery beyond the free tier. This is the single biggest risk to
Ali's lane and it is why the MVP is local-first by design, not by accident. See §7.

---

## 2. Region and location — and why they must agree

**One region: `us-central1`.** Every resource below, with one documented exception.

| Resource | Location | Immutable? | What breaks if it differs |
|---|---|---|---|
| Cloud Run service & jobs | `us-central1` | no | cross-region latency against the <30 s NFR |
| GCS buckets (source, output) | `us-central1` | **yes** | Eventarc refuses to create a trigger whose location differs from the bucket's |
| Eventarc trigger | `us-central1` | no | same as above, from the other side |
| BigQuery dataset | `us-central1` | **yes** | a dataset's location cannot be changed — wrong once means recreate and reload every table |
| Firestore database | `us-central1` | **yes, for the life of the project** | cannot be changed without deleting the database; also pick **Native** mode, not Datastore |
| Artifact Registry | `us-central1` | no | image pulls cross-region on every cold start |
| Pub/Sub topic | global | n/a | — |
| **Document AI processor** | **`us`** (multi-region) | **yes** | ⚠ **the exception.** Doc AI has no `us-central1`; it offers `us` and `eu` only. This mismatch is fine — Doc AI is called over the API with no co-location requirement — but Terraform must pass `us` here and `us-central1` everywhere else, and a single `var.region` used for both will fail |

**Why this matters more than it looks.** Three of these are immutable, and two of them
(BigQuery, Firestore) cost a full teardown to fix. The failure mode is not a clear error —
it is `NOT_FOUND` on a resource that visibly exists in the console, because the client is
looking in a different location. An hour disappears into it.

Terraform: `var.region = "us-central1"` and a separate `var.docai_location = "us"`.
`gcloud config set run/region us-central1` on every machine.

---

## 3. Environment variable names

**Decided: `OPENAI_API_KEY`.** The code reads this name; `.env` must use this name.

> This is not pedantry. On 2026-10-20 `backend/.env` held `OPENAI_KEY=` while
> `backend/engine/config.py` read `OPENAI_API_KEY`. The key was valid, present, and
> completely unreachable — every agent would have reported `NO KEY` with a correct key
> sitting in the file. It is the exact failure Preflight's `env.py` exists to prevent:
> a correct mechanism, a passing test suite, and no caller. Fixed, and recorded here so it
> cannot come back under a different spelling.

| Name | Holds | Notes |
|---|---|---|
| `OPENAI_API_KEY` | inference key | **seed only** — the config store takes ownership on first resolve |
| `OPENROUTER_API_KEY` | bring-your-own-model | optional; normally entered on the Settings page, not a file |
| `GOOGLE_API_KEY` / ADC | Vertex, Doc AI | ADC locally, service account in Cloud Run |
| `ANTHROPIC_API_KEY` | second dialect | optional |
| `CONFIG_STORE` | `sqlite` \| `firestore` | the one switch between local and cloud |
| `CONFIG_DB_PATH` | local SQLite path | local only |
| `GATE_AUTO_THRESHOLD` | `0.90` | seed for the control; the store owns it after first run |
| `GATE_REVIEW_THRESHOLD` | `0.60` | same |
| `ASYNC_PAGE_THRESHOLD` | `15` | route to Doc AI async above this page count |
| `GCP_PROJECT_ID` | `ps12-canon-hackathon26` | |
| `GCP_REGION` | `us-central1` | |
| `DOCAI_LOCATION` | `us` | the §2 exception |
| `VITE_USE_MOCK` | `true` \| `false` | frontend only |
| `VITE_API_URL` | `http://localhost:8000` | frontend only; **every `VITE_*` value is compiled into the public bundle — never a secret** |

---

## 4. Paths and ownership

| Path | Owner | Others may |
|---|---|---|
| `backend/` | Ihsan | read, raise issues |
| `Frontend/` | Tahreem | read |
| `infra/`, `terraform/` | Ali | read |
| `backend/packs/*.yaml` | **the customer's role — Ihsan authors pack v1** | propose, never silently edit |
| `README.md`, `CLAUDE.md`, `docs/` | shared — change by agreement, in a commit that says so | |
| `data/samples/` | frozen | nobody edits the CSVs |

Canonical backend root is **`backend/`**, not `src/`. Rebase on `main` before pushing; a
conflict in someone else's lane goes back to them, it is not resolved for them.

---

## 5. The two gate thresholds

**`auto ≥ 0.90`, `review 0.60–0.90`, `missing < 0.60`.**

These are **stated defaults, not calibrated values**, and we say so on stage. They are not
in the problem statement — PS-12 says only "flag low-confidence mappings for human review
instead of silent errors" and leaves the number to us. Two things follow:

1. They are **controls**, not constants — they live in the config store and the Settings
   page changes them live, which is itself a demonstration of "configurable business rules".
2. They cannot be calibrated against `ps06.needs_review`, because that flag is uncorrelated
   with `extraction_confidence` (flagged 0.61–0.99, unflagged 0.60–0.99 — the same range).
   Any fitting happens against the confirmed golden set, or we call them defaults. **A false
   calibration claim is worse than an honest default.**

---

## 5b. Sampling, and the `active_pack_id` default

**Sampling is per-dialect, decided and verified against the Claude API reference 2026-10-20.**

| Dialect | Send | Determinism rests on |
|---|---|---|
| OpenAI / OpenRouter / Vertex compat | `temperature=0` | temperature + pinned model + structured output |
| Anthropic | **nothing** — omit the field | pinned model + structured output + pinned `effort` |

Current Claude models removed `temperature`/`top_p`/`top_k`: any value is a 400 on Fable
5/5.1, Opus 5.5/5/4.8/4.7 and Sonnet 5; non-default values are a 400 on Sonnet 5.5 and
Haiku 5.5, so `temperature=0` fails there too. `seed` does not exist in that API.
`RoundReport.sampling` records **what was sent**, and a provider change makes two rounds
**not comparable**. OpenAI is our inference provider, so the demo path is unaffected.

**`engine/config.py` defaults `active_pack_id` to `""`, not to a pack name.** A pack id is
a domain noun and Law II forbids one in the engine — the Law II scanner correctly flagged
our own config file. Empty means *discover*: exactly one pack in `packs/` is used; **more
than one with no stored value is a BLOCKED run** naming the packs it found, never a silent
pick of the first. A pack id in the **config store** is data and perfectly fine; in engine
**code** it is not.

## 6. The golden set protocol

`backend/eval/golden_set.csv` — 30 rows, generated by `make_golden_set.py`, five per
institution, each institution using its own vocabulary for the same quantities.

- A row asserts: *given this source label, as this institution writes it in this format,
  the value belongs in this canonical field, with this converted value.*
- `expected_field` is **proposed**; `confirmed_by` is **empty** until a human checks it.
- **A row with an empty `confirmed_by` is not scored**, and the scorer refuses to report
  accuracy with fewer than 30 confirmed rows. That refusal is deliberate: it makes an
  unconfirmed accuracy claim impossible to publish by accident.
- Confirmers: **Ihsan** (field names must match the pack) and **Tahreem** (owns eval).
  Both initials in `confirmed_by`, comma separated.
- Once confirmed, the file is **frozen** for the rest of the event. Scoring against a set
  edited between rounds is not scoring.

---

## 6b. Contract change — `MappingPatchPayload.target_field` (2026-10-20)

**Decided by Ihsan. The only change to `types.ts` so far, and it is additive.**

```ts
target_field?: string;   // added — optional, existing calls unaffected
```

**Why.** `MappingPatchPayload` was `{action, value?, unit?, reason?}`. An analyst could
accept, reject, or edit the *value* — but never say which **field** a value belongs in.
Two consequences, both measured:

- A review row whose `target_field` is empty — which is every review row when the model is
  unavailable, because `Unavailable` correctly routes to `review` — **could never be
  resolved through the API at all.** Demo steps 5 and 6 were not performable without a key.
- The most valuable precedent of all is *"you mapped this to the wrong field, it is this
  one"*, and the contract could not express it. An analyst who can only rate the system's
  guess is not correcting the mapping. Requirement 5 is **analyst corrections feeding back
  into the mapping**, so the payload has to carry the correction, not a verdict on it.

**Frontend impact: none required.** The field is optional; existing accept/reject calls are
unchanged. Tahreem adds a field picker to the review drawer when she wants the full
correction flow — until then the backend accepts it and the UI simply never sends it.

**This does not replace demoing with a key.** With a key the mapper proposes a field and
`accept` works end to end; that is the demo path. `target_field` is what makes the degraded
path and the genuine *correction* case possible.

## 6c. Contract change — record identity (2026-10-20)

**Decided by Ihsan.** Additive and optional, like §6b. No frontend change required.

```ts
Mapping.record_key?:   string   // which row inside the document
Mapping.record_label?: string   // how a human refers to it
ReviewQueueItem.record_key?, .record_label?
```

**Why.** One document holds many records and we were treating it as one. Measured on
`pacific_savings_rates.xlsx`: 60 mappings, 60 distinct cells, **30 distinct spreadsheet
rows**, collapsing into a single `DatasetRecord`. The gold table showed 1/30 of the data,
`render.to_rows` had the same bug so the **export** was equally short, and `ps06`'s 150
records would have rendered as 6 rows. PS-12 asks for "a standardized, validated dataset";
ours was 30× short, and the golden set was unscoreable because 30 rows per institution
cannot match against 1.

It belongs on the contract, not in a repository column, for two reasons:

- **The frontend needs it the moment the gold table is right.** Pacific becomes 30 rows and
  the UI has to know which row each `Mapping` renders into.
- **Without it the backend grows a parallel path** — a `record_key` column plus a
  `list_mapping_rows()` returning pairs beside the existing `list_mappings()` — and the two
  variants drift. A plumbing layer whose only job is to carry a string the contract could
  carry itself is the kind of thing that rots.

**Two fields, not one.** `record_key` is machine identity: deterministic, stable, same
source in and same key out, so the demo cannot drift. `record_label` is what a reviewer
reads — *"Money Market, 12 months"*. A raw `row:31` in the review drawer identifies nothing
a person can go and look at, which is the whole point of the drawer.

**`record_label` comes from the pack, never from us.** A pack may declare which of its
fields identify a record:

```yaml
record_identity: [product_type, term_months]   # optional
  provenance: AUTHORED
  because: "An analyst refers to a rate-sheet row by product and term."
```

No declaration means no label, and the UI falls back to the key. Deriving a label ourselves
would be inventing domain knowledge, which Law III forbids.

**`DatasetRecord.id` changes meaning, not shape** — it stops being the document id and
becomes the record key. No type change needed.

## 7. Open blockers, with owners

| # | Blocker | Owner | Unblocks |
|---|---|---|---|
| B1 | **No open billing account.** Claim the hackathon credits, or open a trial on one of the three logins, then `gcloud billing projects link ps12-canon-hackathon26 --billing-account=<ID>` | Ali + Ihsan | all of Ali's lane |
| B2 | Ali has no IAM on the project yet — the grant command is in §8 | Ihsan (one command) | Ali can start Terraform |
| B3 | Golden set unconfirmed (0 / 30) | Ihsan + Tahreem | every accuracy number |
| B4 | `packs/banking_rates.yaml` not yet authored | Ihsan | the mapper has no target vocabulary |

---

## 8. Commands a human has to run

```bash
# Ihsan — grant Ali access to the project.
#
# ⚠ roles/owner CANNOT be granted by CLI here. On a project with no organization,
# Google requires owners to be INVITED through the Console and returns
# SOLO_MUST_INVITE_OWNERS to gcloud. Measured 2026-10-20.
#
# Use these two instead. They work from the CLI, they are enough for everything in
# Ali's Terraform, and they are least-privilege — which §6 asks for anyway.
# editor alone is NOT enough: Terraform creates google_project_iam_member bindings,
# and editor cannot modify IAM policy.
gcloud projects add-iam-policy-binding ps12-canon-hackathon26 \
  --member="user:muhammadalisajjadakhunzada@gmail.com" --role="roles/editor"
gcloud projects add-iam-policy-binding ps12-canon-hackathon26 \
  --member="user:muhammadalisajjadakhunzada@gmail.com" --role="roles/resourcemanager.projectIamAdmin"

# If Ali genuinely needs owner (he should not for this build):
#   console.cloud.google.com → IAM & Admin → IAM → Grant access → invite, he accepts by email.

# Either — link billing once an account is open
gcloud billing projects link ps12-canon-hackathon26 --billing-account=<OPEN_ACCOUNT_ID>

# Ali — once billing is live
gcloud config set project ps12-canon-hackathon26
gcloud config set run/region us-central1
gcloud auth application-default login
```
