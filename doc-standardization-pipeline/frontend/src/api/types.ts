// ─── Core Status Vocabulary ────────────────────────────────────────────────
export type MappingStatus = 'auto' | 'review' | 'missing' | 'approved' | 'rejected';
export type BatchStage = 'uploading' | 'ingesting' | 'parsing' | 'mapping' | 'normalizing' | 'validating' | 'ready' | 'failed';
export type BatchStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
export type FileStatus = 'ready' | 'uploading' | 'processing' | 'done' | 'error' | 'unsupported';

// ─── Source Location ────────────────────────────────────────────────────────
export interface SourceLocationPdf {
  type: 'pdf';
  page: number;
  bbox: [number, number, number, number]; // [x, y, w, h] normalized 0-1
}
export interface SourceLocationSheet {
  type: 'sheet';
  sheet: string;
  cell: string; // e.g. "B12"
}
export interface SourceLocationText {
  type: 'text';
  start: number;
  end: number;
}
export type SourceLocation = SourceLocationPdf | SourceLocationSheet | SourceLocationText;

// ─── Validation ─────────────────────────────────────────────────────────────
export interface ValidationResult {
  name: string;
  ok: boolean;
  message: string;
}

// ─── Conversion ─────────────────────────────────────────────────────────────
export interface Conversion {
  factor: number;
  rule_id: string;
  formula_text: string;
}

// ─── Mapping ────────────────────────────────────────────────────────────────
export interface Mapping {
  id: string;
  document_id: string;
  /**
   * Which record inside the document this value belongs to — a spreadsheet row, a PDF
   * table row, an HTML <tr>. Deterministic: same source in, same key out.
   *
   * Added 2026-10-20 (docs/AGREEMENTS.md §6c). One document holds many records: Pacific
   * Savings' sheet alone is 30. Without this the gold table can only show one row per
   * document and the dataset is 30x short.
   *
   * Optional because a narrative disclosure may genuinely be one record with no natural
   * key. Absent means "the whole document".
   */
  record_key?: string;
  /**
   * How a human refers to that record — "Money Market, 12 months". For the review drawer:
   * "Rate on pacific_savings_rates.xlsx" does not identify anything a reviewer can go and
   * look at once the sheet has 30 rows, and a raw key like `row:31` does not either.
   *
   * Filled only when the pack declares which fields identify a record. Absent means the
   * UI falls back to record_key.
   */
  record_label?: string;
  source_label: string;
  target_field: string;
  raw_value: string;
  raw_unit?: string;
  value: string;
  unit?: string;
  confidence: number; // 0-1
  status: MappingStatus;
  reason?: string;
  conversion?: Conversion;
  validations: ValidationResult[];
  source_location: SourceLocation;
}

// ─── Batch / Run ────────────────────────────────────────────────────────────
export interface BatchFile {
  id: string;
  name: string;
  type: string;
  size: number;
  status: FileStatus;
  progress?: number; // 0-100
  document_id?: string;
  error?: string;
}

export interface Batch {
  id: string;
  name: string;
  pack_id: string;
  pack_name: string;
  files: BatchFile[];
  stage: BatchStage;
  status: BatchStatus;
  created_at: string;
  updated_at: string;
  stats?: {
    total_files: number;
    total_fields: number;
    auto_approved: number;
    needs_review: number;
    missing: number;
  };
}

// ─── SSE Agent Event ────────────────────────────────────────────────────────
export interface AgentEvent {
  id: string;
  agent: string;
  step: string;
  status: 'running' | 'done' | 'error';
  message: string;
  timestamp: string;
  file_id?: string;
}

// ─── Document ───────────────────────────────────────────────────────────────
export interface Document {
  id: string;
  batch_id: string;
  name: string;
  type: 'pdf' | 'xlsx' | 'csv' | 'html' | 'txt';
  file_url: string;
  page_count?: number;
  status: FileStatus;
  created_at: string;
}

// ─── Schema Pack ────────────────────────────────────────────────────────────
export interface SchemaField {
  name: string;
  label: string;
  type: 'number' | 'string' | 'date' | 'boolean';
  unit?: string;
  required: boolean;
  synonyms: string[];
}

export interface UnitConversion {
  id: string;
  from_unit: string;
  to_unit: string;
  factor: number;
  formula?: string;
}

export interface BusinessRule {
  id: string;
  name: string;
  field: string;
  condition: string;
  action: 'flag' | 'reject' | 'warn';
  description: string;
}

export interface SchemaPack {
  id: string;
  name: string;
  version: string;
  description?: string;
  fields: SchemaField[];
  conversions: UnitConversion[];
  rules: BusinessRule[];
  updated_at: string;
}

// ─── Review Queue ───────────────────────────────────────────────────────────
export interface ReviewQueueItem {
  mapping_id: string;
  document_id: string;
  document_name: string;
  batch_id: string;
  /** See Mapping.record_key. A reviewer cannot act on a field without knowing its record. */
  record_key?: string;
  /** See Mapping.record_label. What the drawer shows above the field. */
  record_label?: string;
  source_label: string;
  target_field: string;
  reason?: string;
  confidence: number;
  status: MappingStatus;
}

// ─── Dataset Record ─────────────────────────────────────────────────────────
export interface DatasetRecord {
  id: string;
  document_id: string;
  document_name: string;
  [field: string]: string | number | boolean | null | undefined;
  _status: MappingStatus;
  _source_page?: number;
  _source_cell?: string;
}

// ─── Insights ───────────────────────────────────────────────────────────────
export interface InsightRun {
  run_id: string;
  date: string;
  mapping_accuracy: number;
  conversion_correctness: number;
  manual_effort_saved: number;
  feedback_improvement: number;
}

export interface LearnedCorrection {
  id: string;
  field: string;
  from_value: string;
  to_value: string;
  document_name: string;
  learned_at: string;
}

export interface Insights {
  mapping_accuracy: number;
  conversion_correctness: number;
  manual_effort_saved: number;
  feedback_improvement: number;
  runs: InsightRun[];
  learned_corrections: LearnedCorrection[];
}

// ─── Health ─────────────────────────────────────────────────────────────────
export interface HealthLayer {
  name: string;
  status: 'ok' | 'degraded' | 'down';
  latency_ms?: number;
  message?: string;
}

export interface HealthStatus {
  overall: 'ok' | 'degraded' | 'down';
  layers: HealthLayer[];
  checked_at: string;
}

// ─── API Responses ──────────────────────────────────────────────────────────
export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  per_page: number;
}

export interface MappingPatchPayload {
  action: 'accept' | 'reject' | 'edit';
  /**
   * The canonical field the analyst says this value belongs in.
   *
   * Added 2026-10-20 (see docs/AGREEMENTS.md §9). Optional and additive — existing
   * accept/reject calls are unaffected. It exists because without it an analyst can
   * rate the system's guess but never correct it: a review row whose target_field is
   * empty (the model was unavailable, or proposed nothing) could never be resolved
   * through the API, and the most valuable precedent of all — "you mapped this to the
   * wrong field, it is THIS one" — was inexpressible. Requirement 5 is analyst
   * corrections feeding back into the mapping, so the contract has to carry the
   * correction, not just a verdict on it.
   */
  target_field?: string;
  value?: string;
  unit?: string;
  reason?: string;
}

export interface MappingPatchResponse {
  mapping: Mapping;
  learned?: boolean;
  learned_message?: string;
}

export interface BulkAcceptPayload {
  document_id: string;
  min_confidence: number; // 0-1
}

export interface BulkAcceptResponse {
  accepted_count: number;
  mappings: Mapping[];
}

export interface CreateBatchPayload {
  pack_id: string;
  url?: string;
}

export interface HomeStats {
  documents_processed: number;
  auto_approved_pct: number;
  fields_needing_review: number;
  mapping_accuracy: number;
  mapping_accuracy_delta: number;
  recent_batches: Batch[];
}
