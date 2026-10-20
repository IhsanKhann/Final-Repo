variable "project_id" {
  description = "The Google Cloud Project ID where resources will be provisioned."
  type        = string
  default     = "doc-standardization-pipeline"
}

variable "region" {
  description = "The Google Cloud region for Cloud Run, Eventarc, and regional storage resources."
  type        = string
  default     = "us-central1"
}

variable "docai_location" {
  description = "The location for Document AI (e.g., 'us' or 'eu')."
  type        = string
  default     = "us"
}

variable "source_bucket_prefix" {
  description = "Prefix for the GCS source documents bucket."
  type        = string
  default     = "docai-source-docs"
}

variable "destination_bucket_prefix" {
  description = "Prefix for the GCS normalized JSON outputs bucket."
  type        = string
  default     = "docai-normalized-json"
}

variable "docai_processor_display_name" {
  description = "Display name for the Document AI Processor."
  type        = string
  default     = "doc-standardization-ocr-processor"
}

variable "docai_processor_type" {
  description = "The type of Document AI processor (e.g. OCR_PROCESSOR, FORM_PARSER_PROCESSOR)."
  type        = string
  default     = "OCR_PROCESSOR"
}

variable "cloud_run_service_name" {
  description = "The name of the Cloud Run backend service."
  type        = string
  default     = "doc-standardization-backend"
}

variable "container_image" {
  description = "The container image URI for the backend service."
  type        = string
  default     = "gcr.io/cloudrun/hello" # Set to your Artifact Registry image after build
}

variable "openai_api_key" {
  description = "OpenAI API Key for agentic mapping and normalization."
  type        = string
  sensitive   = true
  default     = ""
}

variable "bigquery_dataset_id" {
  description = "ID of the BigQuery dataset for normalized records and human review queue."
  type        = string
  default     = "doc_standardization_pipeline"
}
