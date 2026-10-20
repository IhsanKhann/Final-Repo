# -----------------------------------------------------------------------------
# Random Suffix for Globally Unique Bucket Names
# -----------------------------------------------------------------------------
resource "random_id" "suffix" {
  byte_length = 4
}

# -----------------------------------------------------------------------------
# Google Cloud APIs Enablement
# -----------------------------------------------------------------------------
locals {
  required_services = [
    "documentai.googleapis.com",
    "run.googleapis.com",
    "eventarc.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "pubsub.googleapis.com",
    "iam.googleapis.com"
  ]
}

resource "google_project_service" "enabled_apis" {
  for_each                   = toset(locals.required_services)
  project                    = var.project_id
  service                    = each.key
  disable_dependent_services = false
  disable_on_destroy         = false
}

# -----------------------------------------------------------------------------
# Step 1: Google Cloud Storage (GCS) Buckets (2 Buckets)
# -----------------------------------------------------------------------------
resource "google_storage_bucket" "source_documents" {
  name                        = "${var.source_bucket_prefix}-${random_id.suffix.hex}"
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_storage_bucket" "normalized_json" {
  name                        = "${var.destination_bucket_prefix}-${random_id.suffix.hex}"
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.enabled_apis]
}

# -----------------------------------------------------------------------------
# Step 1: Dedicated Service Account & Required IAM Bindings (1 Service Account)
# -----------------------------------------------------------------------------
resource "google_service_account" "pipeline_sa" {
  account_id   = "docai-pipeline-sa"
  display_name = "Document AI & Node.js Pipeline Service Account"
  project      = var.project_id
  depends_on   = [google_project_service.enabled_apis]
}

locals {
  sa_required_roles = [
    "roles/storage.objectAdmin",
    "roles/documentai.apiUser",
    "roles/run.invoker",
    "roles/bigquery.dataEditor",
    "roles/eventarc.eventReceiver"
  ]
}

resource "google_project_iam_member" "sa_bindings" {
  for_each = toset(locals.sa_required_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.pipeline_sa.email}"
}

# Grant GCS service agent pubsub.publisher role to emit storage notifications
data "google_storage_project_service_account" "gcs_account" {
  project = var.project_id
}

resource "google_project_iam_member" "gcs_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}

# -----------------------------------------------------------------------------
# Step 4: Document AI Processor Provisioning (1 Processor)
# -----------------------------------------------------------------------------
resource "google_document_ai_processor" "processor" {
  location     = var.docai_location
  display_name = var.docai_processor_display_name
  type         = var.docai_processor_type
  project      = var.project_id

  depends_on = [google_project_service.enabled_apis]
}

locals {
  processor_id = element(split("/", google_document_ai_processor.processor.name), length(split("/", google_document_ai_processor.processor.name)) - 1)
}

# -----------------------------------------------------------------------------
# Step 5: BigQuery Dataset & Tables (Normalized Records & Review Queue)
# -----------------------------------------------------------------------------
resource "google_bigquery_dataset" "doc_pipeline" {
  dataset_id                  = var.bigquery_dataset_id
  friendly_name               = "Document Standardization Pipeline Dataset"
  description                 = "Stores normalized fields and flagged analyst review items."
  location                    = var.region
  delete_contents_on_destroy  = true
  project                     = var.project_id

  depends_on = [google_project_service.enabled_apis]
}

resource "google_bigquery_table" "normalized_records" {
  dataset_id          = google_bigquery_dataset.doc_pipeline.dataset_id
  table_id            = "normalized_records"
  project             = var.project_id
  deletion_protection = false

  schema = jsonencode([
    { name = "document_id", type = "STRING", mode = "REQUIRED" },
    { name = "source_file", type = "STRING", mode = "REQUIRED" },
    { name = "source_bucket", type = "STRING", mode = "NULLABLE" },
    { name = "document_type", type = "STRING", mode = "NULLABLE" },
    { name = "document_date", type = "STRING", mode = "NULLABLE" },
    { name = "field_name", type = "STRING", mode = "REQUIRED" },
    { name = "raw_value", type = "STRING", mode = "NULLABLE" },
    { name = "standardized_value", type = "STRING", mode = "NULLABLE" },
    { name = "unit", type = "STRING", mode = "NULLABLE" },
    { name = "confidence", type = "FLOAT", mode = "REQUIRED" },
    { name = "requires_human_review", type = "BOOLEAN", mode = "REQUIRED" },
    { name = "reasoning", type = "STRING", mode = "NULLABLE" },
    { name = "processed_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "routing_decision", type = "STRING", mode = "NULLABLE" },
    { name = "rate_limit_retries", type = "INTEGER", mode = "NULLABLE" }
  ])
}

resource "google_bigquery_table" "review_queue" {
  dataset_id          = google_bigquery_dataset.doc_pipeline.dataset_id
  table_id            = "review_queue"
  project             = var.project_id
  deletion_protection = false

  schema = jsonencode([
    { name = "document_id", type = "STRING", mode = "REQUIRED" },
    { name = "source_file", type = "STRING", mode = "REQUIRED" },
    { name = "source_bucket", type = "STRING", mode = "NULLABLE" },
    { name = "document_type", type = "STRING", mode = "NULLABLE" },
    { name = "document_date", type = "STRING", mode = "NULLABLE" },
    { name = "field_name", type = "STRING", mode = "REQUIRED" },
    { name = "raw_value", type = "STRING", mode = "NULLABLE" },
    { name = "standardized_value", type = "STRING", mode = "NULLABLE" },
    { name = "unit", type = "STRING", mode = "NULLABLE" },
    { name = "confidence", type = "FLOAT", mode = "REQUIRED" },
    { name = "requires_human_review", type = "BOOLEAN", mode = "REQUIRED" },
    { name = "reasoning", type = "STRING", mode = "NULLABLE" },
    { name = "processed_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "routing_decision", type = "STRING", mode = "NULLABLE" },
    { name = "rate_limit_retries", type = "INTEGER", mode = "NULLABLE" }
  ])
}

# -----------------------------------------------------------------------------
# Step 4: Cloud Run Service (1 Service, Strictly Enforcing min-instances = 0)
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "backend_service" {
  name     = var.cloud_run_service_name
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.pipeline_sa.email

    scaling {
      # STRICTLY ENFORCE min-instances=0 for on-demand serverless compute
      min_instance_count = 0
      max_instance_count = 10
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      # NO CREDENTIAL IS SET HERE, DELIBERATELY. AGREEMENTS section 1: a key in a Cloud
      # Run env var shows up in `gcloud run services describe` and is baked into the
      # revision, so it cannot be rotated without a redeploy -- the exact failure the
      # config layer exists to prevent. The operator sets the key on the Settings page
      # and Firestore owns it from then on.
      env {
        name  = "CONFIG_STORE"
        value = var.config_store
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_LOCATION"
        value = var.docai_location
      }
      env {
        name  = "DOCAI_PROCESSOR_ID"
        value = local.processor_id
      }
      env {
        name  = "SOURCE_BUCKET_NAME"
        value = google_storage_bucket.source_documents.name
      }
      env {
        name  = "DESTINATION_BUCKET_NAME"
        value = google_storage_bucket.normalized_json.name
      }
      env {
        name  = "BIGQUERY_DATASET_ID"
        value = google_bigquery_dataset.doc_pipeline.dataset_id
      }
      env {
        name  = "BIGQUERY_NORMALIZED_TABLE"
        value = google_bigquery_table.normalized_records.table_id
      }
      env {
        name  = "BIGQUERY_REVIEW_TABLE"
        value = google_bigquery_table.review_queue.table_id
      }
    }
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_project_iam_member.sa_bindings
  ]
}

# Allow Eventarc to invoke Cloud Run backend
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.backend_service.location
  name     = google_cloud_run_v2_service.backend_service.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pipeline_sa.email}"
}

# -----------------------------------------------------------------------------
# Step 4: Eventarc Trigger for GCS Object Finalized Events (1 Trigger)
# -----------------------------------------------------------------------------
resource "google_eventarc_trigger" "gcs_finalize_trigger" {
  name            = "docai-gcs-object-finalized-trigger"
  location        = var.region
  project         = var.project_id
  service_account = google_service_account.pipeline_sa.email

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }

  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.source_documents.name
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_v2_service.backend_service.name
      region  = var.region
      path    = "/api/eventarc-hook"
    }
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_cloud_run_v2_service_iam_member.invoker,
    google_project_iam_member.gcs_pubsub_publisher
  ]
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "source_bucket_name" {
  description = "GCS bucket for incoming source documents."
  value       = google_storage_bucket.source_documents.name
}

output "destination_bucket_name" {
  description = "GCS bucket for normalized JSON output documents."
  value       = google_storage_bucket.normalized_json.name
}

output "service_account_email" {
  description = "IAM Service Account email attached to pipeline resources."
  value       = google_service_account.pipeline_sa.email
}

output "documentai_processor_name" {
  description = "The full resource name of the Document AI Processor."
  value       = google_document_ai_processor.processor.name
}

output "documentai_processor_id" {
  description = "The unique ID of the Document AI Processor."
  value       = local.processor_id
}

output "cloud_run_backend_url" {
  description = "The public URL of the deployed Cloud Run backend service."
  value       = google_cloud_run_v2_service.backend_service.uri
}

output "bigquery_normalized_table" {
  description = "BigQuery table for high-confidence normalized records."
  value       = "${var.project_id}.${google_bigquery_dataset.doc_pipeline.dataset_id}.${google_bigquery_table.normalized_records.table_id}"
}

output "bigquery_review_queue_table" {
  description = "BigQuery table for human review queue."
  value       = "${var.project_id}.${google_bigquery_dataset.doc_pipeline.dataset_id}.${google_bigquery_table.review_queue.table_id}"
}


# --- Added for the PS-12 deployment -------------------------------------------
# Firestore is NOT optional. The config layer is what makes a credential survive a
# redeploy, and on Cloud Run a sqlite store lives on an ephemeral disk and dies with
# the revision -- which would make the claim false in the one place we demonstrate it.

resource "google_firestore_database" "config" {
  project = var.project_id
  name    = "(default)"
  # NATIVE, not DATASTORE_MODE. Neither this nor the location can be changed later
  # without deleting the database -- AGREEMENTS section 2.
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.enabled_apis]
}

resource "google_artifact_registry_repository" "backend" {
  project       = var.project_id
  location      = var.region
  repository_id = "backend"
  description   = "Container images for the standardization backend"
  format        = "DOCKER"

  depends_on = [google_project_service.enabled_apis]
}

# The SEED only. The store takes ownership on first resolve and Settings owns it after
# that; this exists so a fresh project is not dead on arrival.
resource "google_secret_manager_secret" "openai_api_key" {
  project   = var.project_id
  secret_id = "openai-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_pubsub_topic" "documents" {
  project = var.project_id
  name    = "documents"

  depends_on = [google_project_service.enabled_apis]
}

# --- The three tables the evidence, feedback and round claims rest on ----------

resource "google_bigquery_table" "evidence_ledger" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.doc_pipeline.dataset_id
  table_id            = "evidence_ledger"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "ts"
  }
  clustering = ["tenant_id", "batch_id"]

  schema = jsonencode([
    { name = "field_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
    { name = "batch_id", type = "STRING", mode = "NULLABLE" },
    { name = "document_id", type = "STRING", mode = "NULLABLE" },
    { name = "record_key", type = "STRING", mode = "NULLABLE" },
    { name = "doc_sha256", type = "STRING", mode = "NULLABLE" },
    { name = "canonical_field", type = "STRING", mode = "NULLABLE" },
    { name = "value", type = "STRING", mode = "NULLABLE" },
    { name = "unit", type = "STRING", mode = "NULLABLE" },
    { name = "as_reported", type = "STRING", mode = "NULLABLE" },
    { name = "source_page", type = "INTEGER", mode = "NULLABLE" },
    { name = "source_bbox", type = "FLOAT", mode = "REPEATED" },
    { name = "source_cell", type = "STRING", mode = "NULLABLE" },
    { name = "authority", type = "STRING", mode = "NULLABLE" },
    { name = "pack_version", type = "STRING", mode = "NULLABLE" },
    { name = "rule_id", type = "STRING", mode = "NULLABLE" },
    { name = "conversion_factor", type = "FLOAT", mode = "NULLABLE" },
    { name = "confidence", type = "FLOAT", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "NULLABLE" },
    { name = "reason", type = "STRING", mode = "NULLABLE" },
    { name = "model", type = "STRING", mode = "NULLABLE" },
    { name = "prompt_version", type = "STRING", mode = "NULLABLE" },
    { name = "sampling", type = "STRING", mode = "NULLABLE" },
    { name = "round", type = "INTEGER", mode = "NULLABLE" },
    { name = "reviewed_by", type = "STRING", mode = "NULLABLE" },
    { name = "approved_by", type = "STRING", mode = "NULLABLE" },
    { name = "ts", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "feedback_events" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.doc_pipeline.dataset_id
  table_id            = "feedback_events"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "ts"
  }
  clustering = ["tenant_id"]

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
    { name = "field_id", type = "STRING", mode = "NULLABLE" },
    { name = "reviewer", type = "STRING", mode = "NULLABLE" },
    { name = "action", type = "STRING", mode = "NULLABLE" },
    { name = "source_label", type = "STRING", mode = "NULLABLE" },
    { name = "corrected_field", type = "STRING", mode = "NULLABLE" },
    { name = "corrected_value", type = "STRING", mode = "NULLABLE" },
    { name = "note", type = "STRING", mode = "NULLABLE" },
    { name = "ts", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "round_reports" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.doc_pipeline.dataset_id
  table_id            = "round_reports"
  deletion_protection = false

  schema = jsonencode([
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
    { name = "round", type = "INTEGER", mode = "NULLABLE" },
    { name = "pack_version", type = "STRING", mode = "NULLABLE" },
    { name = "provider", type = "STRING", mode = "NULLABLE" },
    { name = "model", type = "STRING", mode = "NULLABLE" },
    { name = "sampling", type = "STRING", mode = "NULLABLE" },
    { name = "prompt_version", type = "STRING", mode = "NULLABLE" },
    { name = "docs", type = "INTEGER", mode = "NULLABLE" },
    { name = "fields", type = "INTEGER", mode = "NULLABLE" },
    { name = "auto_accepted", type = "INTEGER", mode = "NULLABLE" },
    { name = "flagged", type = "INTEGER", mode = "NULLABLE" },
    { name = "missing", type = "INTEGER", mode = "NULLABLE" },
    { name = "mapping_accuracy", type = "FLOAT", mode = "NULLABLE" },
    { name = "conversion_correctness", type = "FLOAT", mode = "NULLABLE" },
    { name = "precedents_applied", type = "INTEGER", mode = "NULLABLE" },
    { name = "model_calls_skipped", type = "INTEGER", mode = "NULLABLE" },
    { name = "analyst_minutes_saved", type = "FLOAT", mode = "NULLABLE" },
    { name = "cost_usd", type = "FLOAT", mode = "NULLABLE" },
    { name = "ts", type = "TIMESTAMP", mode = "NULLABLE" },
  ])
}

output "service_url" {
  value       = google_cloud_run_v2_service.backend_service.uri
  description = "Public URL of the backend."
}

output "processor_id" {
  value       = local.processor_id
  description = "Document AI processor id. Goes into the CONFIG STORE, not into .env."
}

output "source_bucket" {
  value = google_storage_bucket.source_documents.name
}

output "dataset_id" {
  value = google_bigquery_dataset.doc_pipeline.dataset_id
}
