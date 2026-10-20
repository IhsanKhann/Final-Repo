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
# Ihsan — grant Ali access to the project (blocked for the agent, needs a human)
gcloud projects add-iam-policy-binding ps12-canon-hackathon26 \
  --member="user:muhammadalisajjadakhunzada@gmail.com" --role="roles/owner"

# Either — link billing once an account is open
gcloud billing projects link ps12-canon-hackathon26 --billing-account=<OPEN_ACCOUNT_ID>

# Ali — once billing is live
gcloud config set project ps12-canon-hackathon26
gcloud config set run/region us-central1
gcloud auth application-default login
```
