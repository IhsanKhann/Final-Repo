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

      env {
        name  = "OPENAI_API_KEY"
        value = var.openai_api_key
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
