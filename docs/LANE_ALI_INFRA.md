# Lane: Ali — Infrastructure, Deployment, Scalability, Credentials

**Read [`../README.md`](../README.md) first** — it is the standard and carries the problem
statement. This file is only your lane. Where they disagree, the README wins.

Your branch work is already on `alibranch` (`d1094ee`) and it is good: Terraform for 2
buckets, service account + IAM, a Document AI processor, a BigQuery dataset with
`normalized_records` and `review_queue`, a Cloud Run v2 service and an Eventarc finalize
trigger. **Keep all of that.** One change of direction only: we run **one Python backend**,
not the Express app — so your Terraform stays, your `app.js` becomes the deployment
reference rather than the running service.

---

## 0. Your one-line job

**Make a credential or a setting changeable without a redeploy, make the pipeline scale to
a burst without a code change, and make the whole thing deployable with one command — twice,
reliably, because we will deploy under time pressure.**

---

## 1. The non-negotiable: credentials must survive redeploys

This is the part of your lane the rest of the build depends on. At a previous hackathon a
key ran out mid-build and every fix cost a ten-minute redeploy. That must be impossible here.

### The rule

```
control(key)      session -> database -> env -> default        # chains freely
secret_for(id)    session -> database -> env SEED (once)       # then STOPS
```

- A **control** is a policy decision — provider, model, max tokens, timeout, the two gate
  thresholds, bucket names, processor id. Chaining to env and then a default is correct.
- A **secret** is not. Env is a **seed**: the first resolution with nothing stored promotes
  the env value into the database, labelled `env-seed`, and after that **the database owns
  it and env is never read again**. Without this rule, the key you paste dies, the stale one
  in the environment quietly answers, and the Health page still says connected.
- **An explicit empty value is a value.** A stored `""` stops the chain exactly like a key
  does — otherwise clearing a key is impossible and "no key configured" is unsayable.
- **Last-known-good covers controls only, never secrets.** On a credential it would
  resurrect a key the operator had just revoked.

Ihsan implements the resolver in `backend/engine/config.py`. **You own the store behind it
and the fact that it survives.**

### The store

```sql
-- local dev: SQLite file.  cloud: Firestore collections. Same interface either way.
config  (tenant_id, key,  value,      source, updated_by, updated_at)
secrets (tenant_id, id,   value_enc,  source, updated_by, updated_at)
```

**Firestore, not BigQuery, for this one.** Config reads happen on the hot path and need
point reads and immediate consistency; BigQuery is an analytics store with streaming-insert
latency and no cheap single-row update. Two collections:

```
tenants/{tenant_id}/config/{key}     { value, source, updated_by, updated_at }
tenants/{tenant_id}/secrets/{id}     { value_enc, source, updated_by, updated_at }
```

`value_enc` is encrypted with a **Cloud KMS** key, or — if KMS costs you more than fifteen
minutes — stored in **Secret Manager** with the Firestore document holding only the secret
*name* and version. Either is defensible; pick the one you can finish. Never store a raw
key in a Firestore document and never log a secret value, even truncated.

### Deploy-survival checklist (this is the demo-able claim)

- [ ] `terraform apply` → write the processor id and bucket names **into the config store**,
      not into `.env` and not into the image
- [ ] Change the OpenAI key on the Settings page → the **very next** request uses it
- [ ] `gcloud run deploy` a new revision → the key is still there, no re-entry, no redeploy
- [ ] Delete the key on the Settings page → Health goes `degraded` with `no-key`, and does
      **not** silently fall back to an environment variable
- [ ] Nothing in `gcloud run services describe` env vars is a credential

That fourth box is the one that proves the rule. Demonstrate it.

---

## 2. Terraform — what exists and what to add

Already on `alibranch/doc-standardization-pipeline/terraform/main.tf`:

| Resource | Status |
|---|---|
| `google_project_service.enabled_apis` | ✅ keep |
| `google_storage_bucket.source_documents` / `.normalized_json` | ✅ keep |
| `google_service_account.pipeline_sa` + IAM bindings | ✅ keep |
| `google_document_ai_processor.processor` | ✅ keep |
| `google_bigquery_dataset` + `normalized_records` + `review_queue` | ✅ keep, **extend schema** (below) |
| `google_cloud_run_v2_service.backend_service` | ✅ keep, **point at the Python image** |
| `google_eventarc_trigger.gcs_finalize_trigger` | ✅ keep |

To add:

```hcl
# Firestore in Native mode — the config/secrets store
resource "google_firestore_database" "default" { ... location_id = var.region, type = "FIRESTORE_NATIVE" }

# Secret Manager for the seed values
resource "google_secret_manager_secret" "openai_api_key" { ... }

# Pub/Sub topic + Cloud Run JOB for parallel fan-out (one container per document)
resource "google_pubsub_topic" "documents" { ... }
resource "google_cloud_run_v2_job" "worker" { ... }

# Artifact Registry for the backend image
resource "google_artifact_registry_repository" "backend" { format = "DOCKER" }
```

IAM for `pipeline_sa` — least privilege, exactly these:

```
roles/storage.objectAdmin        on the two buckets only, not project-wide
roles/documentai.apiUser
roles/bigquery.dataEditor        on the one dataset
roles/datastore.user             Firestore config store
roles/secretmanager.secretAccessor
roles/run.invoker                Eventarc -> Cloud Run
roles/pubsub.publisher           fan-out
```

**`min_instances = 0` on the Cloud Run service.** Idle costs nothing; a burst spawns
containers on demand. That is the scalability story and it is one line.

### Terraform hygiene under time pressure

- Remote state in a GCS bucket from the first apply. Local state will be lost or conflict.
- `terraform plan` output pasted into the group chat before any `apply` that touches an
  existing resource.
- Everything environment-specific is a variable with a default; no hardcoded project id.
- Outputs are the handoff: `processor_id`, `source_bucket`, `output_bucket`, `dataset_id`,
  `service_url`. Ihsan reads them from the config store, not from your terminal.

---

## 3. BigQuery schema — extend what you have

`normalized_records` and `review_queue` exist. Add the three below; they are what make the
product's claims provable.

```sql
-- 1. evidence_ledger: one row per mapped cell, APPEND ONLY. Never UPDATE, never DELETE.
CREATE TABLE evidence_ledger (
  field_id        STRING   NOT NULL,
  tenant_id       STRING   NOT NULL,
  batch_id        STRING,
  document_id     STRING,
  doc_sha256      STRING,
  canonical_field STRING,
  value           STRING,
  unit            STRING,
  as_reported     STRING,
  source_page     INT64,
  source_bbox     ARRAY<FLOAT64>,   -- normalized 0-1 [x,y,w,h]
  source_cell     STRING,
  authority       STRING,           -- PACK_QUOTED|PACK_AUTHORED|ANALYST|MODEL
  pack_version    STRING,
  rule_id         STRING,
  conversion_factor FLOAT64,
  confidence      FLOAT64,
  status          STRING,           -- auto|review|missing|approved|rejected
  reason          STRING,
  model           STRING,
  prompt_version  STRING,
  temperature     FLOAT64,
  round           INT64,
  reviewed_by     STRING,
  approved_by     STRING,
  ts              TIMESTAMP NOT NULL
) PARTITION BY DATE(ts) CLUSTER BY tenant_id, batch_id;

-- 2. feedback_events: every analyst action
CREATE TABLE feedback_events (
  event_id STRING, tenant_id STRING, field_id STRING, reviewer STRING,
  action STRING,          -- accept|reject|edit
  source_label STRING, corrected_field STRING, corrected_value STRING,
  note STRING, ts TIMESTAMP
) PARTITION BY DATE(ts) CLUSTER BY tenant_id;

-- 3. round_reports: the improvement proof
CREATE TABLE round_reports (
  run_id STRING, tenant_id STRING, round INT64, pack_version STRING,
  model STRING, temperature FLOAT64, prompt_version STRING, docs INT64, fields INT64,
  auto_accepted INT64, flagged INT64, missing INT64,
  mapping_accuracy FLOAT64, conversion_correctness FLOAT64,
  precedents_applied INT64, model_calls_skipped INT64,
  analyst_minutes_saved FLOAT64, cost_usd FLOAT64, ts TIMESTAMP
);
```

**Append-only is a product feature, not a style preference.** Re-runs add a version; they
never overwrite. That is what buys replay, audit, and the improvement chart.

---

## 4. Deployment

### Local (what the team uses today)

```bash
# Backend
cd backend && uvicorn api.main:app --reload --port 8000
# Frontend
cd Frontend && npm run dev          # http://localhost:5173
```

Local uses SQLite for config and the local filesystem for storage, behind the same
interfaces. **Nobody should need a GCP account to run the project.** That is your
constraint too: if a teammate must authenticate to GCP to see the app work, the seam is
in the wrong place.

### Cloud

```bash
gcloud auth login
gcloud config set project $PROJECT_ID

cd infra
terraform init && terraform plan -out=tf.plan && terraform apply tf.plan

# build + push the Python backend
gcloud builds submit backend --tag $REGION-docker.pkg.dev/$PROJECT_ID/backend/canon:$(git rev-parse --short HEAD)
gcloud run deploy canon-backend \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/backend/canon:$(git rev-parse --short HEAD) \
  --region $REGION --min-instances 0 --max-instances 20 \
  --service-account pipeline-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars CONFIG_STORE=firestore,GCP_PROJECT_ID=$PROJECT_ID
  # NOTE: no credentials in env vars. Ever.
```

Frontend: `npm run build` → deploy `Frontend/dist` to Firebase Hosting or a GCS bucket
behind Cloud CDN, with `VITE_API_URL` pointing at the Cloud Run URL at build time.

### CI/CD (Cloud Build, one file)

`cloudbuild.yaml` on push to `main`: run `pytest backend/tests` → **fail the build if any
of the five law tests fail** → build image → deploy to Cloud Run. The law tests in CI are
the cheapest guarantee the engine stays clean while three people commit fast.

---

## 5. Scalability and the non-functional requirements

| Requirement | Target | How you meet it |
|---|---|---|
| Scalability | 1 → 10,000 docs/day, no code change | Eventarc on `object.finalized` publishes to Pub/Sub; a Cloud Run **job** processes one document per container; `max-instances` is the only knob |
| Latency | < 30 s for a 5-page text PDF | Cheap adapter when the text layer is good; Doc AI async (`batch_process_documents`) for anything over 15 pages |
| Throughput | linear in container count | No shared mutable state between documents; config reads are Firestore point reads |
| Availability | degrades, never fails | Provider outage → precedents still resolve, remainder queues, Health says `degraded`. A run always produces a result |
| Cost | falls per document across rounds | `min-instances 0`; precedent hits skip the model entirely; token budget per document; cost logged per run |
| Reproducibility | same inputs + versions → same output | Deterministic engine, temperature 0, pinned model, append-only ledger |
| Auditability | every cell traceable to a page | `evidence_ledger`, partitioned and clustered |
| Security | tenant isolation, least privilege, no secrets in images | Per-tenant GCS prefix `gs://bucket/{tenant_id}/...`, `tenant_id` on every row, one scoped SA, Secret Manager |
| Observability | every run explainable without a debugger | Structured JSON logs: `routing_decision`, `rate_limit_retries`, `fields_flagged_for_review`, `tokens`, `cost_usd`, `round` |

### Load test you should actually run (10 minutes, and it is a slide)

```bash
# 50 PDFs into the source bucket at once
for i in $(seq 1 50); do gsutil cp sample.pdf gs://$SOURCE_BUCKET/loadtest/doc_$i.pdf & done; wait
# then capture: containers spawned, wall-clock to completion, cost
gcloud logging read 'resource.type="cloud_run_revision"' --limit 200 --format json > loadtest.json
```

Put the number on a slide: *"50 documents in parallel, N containers, M seconds, $X."*

---

## 6. Guardrails you own

- **Quota at ingest** — pages per tenant per month, checked **before** any processing cost.
  This is the Free-tier limit and the only billing rule enforced in the MVP.
- **MIME allow-list** — everything else refused with a reason, not silently dropped.
- **Size and page ceilings** per tier, checked before download.
- **`sha256` dedup** — the same file twice is one record and one bill. It is also what
  makes every retry safe.
- **Eventarc retry policy** — bounded, with a dead-letter topic. An un-dead-lettered
  trigger will reprocess a poison document forever and spend the credits.
- **Secret Manager only** — no credential in an env var, a Dockerfile, or a log line.

---

## 7. What you hand to Ihsan, and when

| Hand over | Format | When |
|---|---|---|
| `processor_id`, bucket names, dataset id | written **into the config store**, plus a message | right after the first `terraform apply` |
| Service account JSON for local dev | a file, over a private channel, **never in git** | when he needs Doc AI locally |
| Cloud Run service URL | message | after first deploy — Tahreem needs it for `VITE_API_URL` |
| BigQuery dataset + the three new tables | DDL applied | before round reports are written |

---

## 8. Your manual steps (nobody can automate these for you)

1. Create the GCP project and **enable billing** — the credits must be attached before
   `terraform apply`, or half the resources fail with confusing errors.
2. `gcloud auth login` and `gcloud auth application-default login` on your own machine.
3. Enable the APIs: Document AI, Cloud Run, Eventarc, Pub/Sub, BigQuery, Firestore,
   Secret Manager, Artifact Registry, Cloud Build. (Terraform does this, but the first
   enable can take minutes — do it early.)
4. Create the Firestore database in **Native** mode. This cannot be changed later without
   deleting it; choose Native, not Datastore mode.
5. Create the remote-state GCS bucket before the first `terraform init`.
6. Put the OpenAI key into Secret Manager as the **seed** — Ihsan's resolver promotes it
   into the config store on first run, and from then on the Settings page owns it.
7. Pick the region once and tell the group. Doc AI, Firestore, Cloud Run and the buckets
   must agree, and fixing a mismatch later costs a rebuild.

---

## 9. Done looks like

- [ ] `terraform apply` from clean, twice, with no manual console step
- [ ] Backend deployed, `GET /api/health` returns 200 over the public URL
- [ ] A file dropped in the source bucket produces a row in `evidence_ledger`
- [ ] Key changed on the Settings page takes effect on the next request, with **no redeploy**
- [ ] A new revision deployed — the key is still there
- [ ] 50-document load test captured with timing and cost
- [ ] CI runs the five law tests and blocks the deploy if one is red
- [ ] No credential anywhere in `git log -p`
