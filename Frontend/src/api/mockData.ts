import type {
  Batch, Mapping, ReviewQueueItem, Insights, HealthStatus,
  SchemaPack, HomeStats, DatasetRecord,
} from './types';

// ─── Mock Schema Packs ──────────────────────────────────────────────────────
export const MOCK_PACKS: SchemaPack[] = [
  {
    id: 'mining-v1',
    name: 'Mining',
    version: '1.0',
    description: 'Metals & mining production reports',
    fields: [
      { name: 'production_t', label: 'Production (t)', type: 'number', unit: 't', required: true, synonyms: ['output', 'yield', 'production'] },
      { name: 'unit_cost', label: 'Unit Cost ($/t)', type: 'number', unit: '$/t', required: true, synonyms: ['cash cost', 'opex', 'cost per unit'] },
      { name: 'site_name', label: 'Site Name', type: 'string', required: true, synonyms: ['mine name', 'operation', 'project'] },
      { name: 'period', label: 'Reporting Period', type: 'string', required: true, synonyms: ['quarter', 'period', 'date range'] },
    ],
    conversions: [
      { id: 'lb-t', from_unit: 'lb', to_unit: 't', factor: 0.000453592, formula: 'value × 0.000453592' },
      { id: 'usd-lb-usd-t', from_unit: '$/lb', to_unit: '$/t', factor: 2204.62, formula: 'value × 2204.62' },
      { id: 'oz-t', from_unit: 'oz', to_unit: 't', factor: 0.0000283495, formula: 'value × 0.0000283495' },
    ],
    rules: [
      { id: 'r1', name: 'Non-negative production', field: 'production_t', condition: 'value >= 0', action: 'reject', description: 'Production cannot be negative' },
      { id: 'r2', name: 'Reasonable cost', field: 'unit_cost', condition: 'value < 100000', action: 'flag', description: 'Flag unusually high unit costs' },
    ],
    updated_at: '2026-10-15T10:00:00Z',
  },
  {
    id: 'shipping-v1',
    name: 'Shipping',
    version: '1.0',
    description: 'Freight & logistics rate sheets',
    fields: [
      { name: 'freight_rate', label: 'Freight Rate ($/TEU)', type: 'number', unit: '$/TEU', required: true, synonyms: ['rate', 'tariff', 'freight cost'] },
      { name: 'origin_port', label: 'Origin Port', type: 'string', required: true, synonyms: ['from', 'departure', 'POL'] },
      { name: 'dest_port', label: 'Destination Port', type: 'string', required: true, synonyms: ['to', 'arrival', 'POD'] },
      { name: 'transit_days', label: 'Transit Time (days)', type: 'number', required: false, synonyms: ['transit', 'sailing time', 'ETD'] },
    ],
    conversions: [],
    rules: [],
    updated_at: '2026-10-14T08:00:00Z',
  },
  {
    id: 'finance-v1',
    name: 'Finance',
    version: '1.0',
    description: 'Financial disclosure reports',
    fields: [
      { name: 'revenue', label: 'Revenue ($M)', type: 'number', unit: '$M', required: true, synonyms: ['turnover', 'income', 'sales'] },
      { name: 'ebitda', label: 'EBITDA ($M)', type: 'number', unit: '$M', required: true, synonyms: ['operating profit', 'earnings'] },
    ],
    conversions: [
      { id: 'k-m', from_unit: '$K', to_unit: '$M', factor: 0.001, formula: 'value × 0.001' },
      { id: 'b-m', from_unit: '$B', to_unit: '$M', factor: 1000, formula: 'value × 1000' },
    ],
    rules: [],
    updated_at: '2026-10-13T09:00:00Z',
  },
];

// ─── Mock Batches ────────────────────────────────────────────────────────────
export const MOCK_BATCHES: Batch[] = [
  {
    id: 'batch-001',
    name: 'Q3 Mining Reports',
    pack_id: 'mining-v1',
    pack_name: 'Mining v1',
    files: [
      { id: 'f1', name: 'rates_q3.xlsx', type: 'Excel', size: 204800, status: 'done', progress: 100, document_id: 'doc-001' },
      { id: 'f2', name: 'filing.pdf', type: 'PDF (scan)', size: 1048576, status: 'done', progress: 100, document_id: 'doc-002' },
      { id: 'f3', name: 'notes.html', type: 'HTML', size: 51200, status: 'done', progress: 100, document_id: 'doc-003' },
    ],
    stage: 'ready',
    status: 'done',
    created_at: '2026-10-19T08:00:00Z',
    updated_at: '2026-10-19T09:32:00Z',
    stats: { total_files: 3, total_fields: 42, auto_approved: 30, needs_review: 9, missing: 3 },
  },
  {
    id: 'batch-002',
    name: 'Shipping Rate Sheets',
    pack_id: 'shipping-v1',
    pack_name: 'Shipping v1',
    files: [
      { id: 'f4', name: 'rates_oct.csv', type: 'CSV', size: 102400, status: 'done', progress: 100, document_id: 'doc-004' },
    ],
    stage: 'ready',
    status: 'done',
    created_at: '2026-10-18T14:00:00Z',
    updated_at: '2026-10-18T14:45:00Z',
    stats: { total_files: 1, total_fields: 18, auto_approved: 16, needs_review: 2, missing: 0 },
  },
  {
    id: 'batch-003',
    name: 'Finance Disclosures',
    pack_id: 'finance-v1',
    pack_name: 'Finance v1',
    files: [
      { id: 'f5', name: 'annual_report.pdf', type: 'PDF', size: 3145728, status: 'processing', progress: 62, document_id: 'doc-005' },
    ],
    stage: 'mapping',
    status: 'running',
    created_at: '2026-10-20T10:00:00Z',
    updated_at: '2026-10-20T10:22:00Z',
    stats: { total_files: 1, total_fields: 0, auto_approved: 0, needs_review: 0, missing: 0 },
  },
];

// ─── Mock Mappings ───────────────────────────────────────────────────────────
export const MOCK_MAPPINGS: Mapping[] = [
  {
    id: 'm1',
    document_id: 'doc-001',
    source_label: 'Nickel production',
    target_field: 'production_t',
    raw_value: '12,500',
    raw_unit: 'lb',
    value: '5.67',
    unit: 't',
    confidence: 0.96,
    status: 'auto',
    validations: [{ name: 'Non-negative production', ok: true, message: 'Passes' }],
    conversion: { factor: 0.000453592, rule_id: 'lb-t', formula_text: '12,500 lb × 0.000453592 = 5.67 t' },
    source_location: { type: 'pdf', page: 3, bbox: [0.1, 0.22, 0.5, 0.04] },
  },
  {
    id: 'm2',
    document_id: 'doc-001',
    source_label: 'Cash cost',
    target_field: 'unit_cost',
    raw_value: '$4.2',
    raw_unit: '$/lb',
    value: '9259',
    unit: '$/t',
    confidence: 0.61,
    status: 'review',
    reason: 'Footnote conflict: value may exclude royalties. Verify before accepting.',
    validations: [
      { name: 'Non-negative cost', ok: true, message: 'Passes' },
      { name: 'Reasonable cost', ok: true, message: 'Within expected range' },
    ],
    conversion: { factor: 2204.62, rule_id: 'usd-lb-usd-t', formula_text: '$4.2/lb × 2204.62 lb/t = $9,259/t (rule #3)' },
    source_location: { type: 'pdf', page: 3, bbox: [0.1, 0.30, 0.55, 0.04] },
  },
  {
    id: 'm3',
    document_id: 'doc-001',
    source_label: 'Mine name',
    target_field: 'site_name',
    raw_value: 'Voisey\'s Bay',
    raw_unit: undefined,
    value: 'Voisey\'s Bay',
    unit: undefined,
    confidence: 0.94,
    status: 'auto',
    validations: [{ name: 'Required field present', ok: true, message: 'Passes' }],
    source_location: { type: 'pdf', page: 1, bbox: [0.1, 0.08, 0.45, 0.04] },
  },
  {
    id: 'm4',
    document_id: 'doc-001',
    source_label: 'Not found',
    target_field: 'period',
    raw_value: '',
    raw_unit: undefined,
    value: '',
    unit: undefined,
    confidence: 0,
    status: 'missing',
    reason: 'Reporting period not found in document. Enter manually.',
    validations: [{ name: 'Required field present', ok: false, message: 'Missing required field' }],
    source_location: { type: 'text', start: 0, end: 0 },
  },
  {
    id: 'm5',
    document_id: 'doc-002',
    source_label: 'Production output',
    target_field: 'production_t',
    raw_value: '8,200',
    raw_unit: 'lb',
    value: '3.72',
    unit: 't',
    confidence: 0.88,
    status: 'review',
    reason: 'Low OCR confidence on source page. Verify value.',
    validations: [{ name: 'Non-negative production', ok: true, message: 'Passes' }],
    conversion: { factor: 0.000453592, rule_id: 'lb-t', formula_text: '8,200 lb × 0.000453592 = 3.72 t' },
    source_location: { type: 'pdf', page: 2, bbox: [0.2, 0.45, 0.4, 0.04] },
  },
  {
    id: 'm6',
    document_id: 'doc-002',
    source_label: 'Site',
    target_field: 'site_name',
    raw_value: 'Thompson Mine',
    value: 'Thompson Mine',
    confidence: 0.91,
    status: 'auto',
    validations: [{ name: 'Required field present', ok: true, message: 'Passes' }],
    source_location: { type: 'pdf', page: 1, bbox: [0.1, 0.10, 0.4, 0.04] },
  },
];

// ─── Mock Review Queue ──────────────────────────────────────────────────────
export const MOCK_REVIEW_QUEUE: ReviewQueueItem[] = [
  {
    mapping_id: 'm2',
    document_id: 'doc-001',
    document_name: 'rates_q3.xlsx',
    batch_id: 'batch-001',
    source_label: 'Cash cost',
    target_field: 'unit_cost',
    reason: 'Footnote conflict: value may exclude royalties',
    confidence: 0.61,
    status: 'review',
  },
  {
    mapping_id: 'm4',
    document_id: 'doc-001',
    document_name: 'rates_q3.xlsx',
    batch_id: 'batch-001',
    source_label: 'Not found',
    target_field: 'period',
    reason: 'Missing required field',
    confidence: 0,
    status: 'missing',
  },
  {
    mapping_id: 'm5',
    document_id: 'doc-002',
    document_name: 'filing.pdf',
    batch_id: 'batch-001',
    source_label: 'Production output',
    target_field: 'production_t',
    reason: 'Low OCR confidence',
    confidence: 0.88,
    status: 'review',
  },
];

// ─── Mock Insights ────────────────────────────────────────────────────────────
export const MOCK_INSIGHTS: Insights = {
  mapping_accuracy: 0.91,
  conversion_correctness: 0.96,
  manual_effort_saved: 0.73,
  feedback_improvement: 0.08,
  runs: [
    { run_id: 'r1', date: '2026-10-10', mapping_accuracy: 0.78, conversion_correctness: 0.88, manual_effort_saved: 0.60, feedback_improvement: 0 },
    { run_id: 'r2', date: '2026-10-13', mapping_accuracy: 0.83, conversion_correctness: 0.91, manual_effort_saved: 0.65, feedback_improvement: 0.05 },
    { run_id: 'r3', date: '2026-10-16', mapping_accuracy: 0.87, conversion_correctness: 0.93, manual_effort_saved: 0.69, feedback_improvement: 0.06 },
    { run_id: 'r4', date: '2026-10-19', mapping_accuracy: 0.91, conversion_correctness: 0.96, manual_effort_saved: 0.73, feedback_improvement: 0.08 },
  ],
  learned_corrections: [
    { id: 'lc1', field: 'unit_cost', from_value: '$4.2/lb', to_value: '$9259/t', document_name: 'rates_q3.xlsx', learned_at: '2026-10-19T10:00:00Z' },
    { id: 'lc2', field: 'production_t', from_value: '8200 lb', to_value: '3.72 t', document_name: 'filing.pdf', learned_at: '2026-10-19T11:00:00Z' },
  ],
};

// ─── Mock Health ──────────────────────────────────────────────────────────────
export const MOCK_HEALTH: HealthStatus = {
  overall: 'ok',
  layers: [
    { name: 'Document AI', status: 'ok', latency_ms: 120 },
    { name: 'Vertex AI (Gemini)', status: 'ok', latency_ms: 340 },
    { name: 'Cloud Storage', status: 'ok', latency_ms: 45 },
    { name: 'BigQuery', status: 'ok', latency_ms: 88 },
    { name: 'API Gateway', status: 'ok', latency_ms: 15 },
  ],
  checked_at: new Date().toISOString(),
};

// ─── Mock Home Stats ─────────────────────────────────────────────────────────
export const MOCK_HOME_STATS: HomeStats = {
  documents_processed: 47,
  auto_approved_pct: 0.82,
  fields_needing_review: 11,
  mapping_accuracy: 0.91,
  mapping_accuracy_delta: 0.04,
  recent_batches: MOCK_BATCHES,
};

// ─── Mock Dataset Records ────────────────────────────────────────────────────
export const MOCK_RECORDS: DatasetRecord[] = [
  { id: 'rec-1', document_id: 'doc-001', document_name: 'rates_q3.xlsx', site_name: "Voisey's Bay", production_t: 5.67, unit_cost: 9259, _status: 'review', _source_page: 3 },
  { id: 'rec-2', document_id: 'doc-002', document_name: 'filing.pdf', site_name: 'Thompson Mine', production_t: 3.72, unit_cost: null, _status: 'review', _source_page: 2 },
  { id: 'rec-3', document_id: 'doc-003', document_name: 'notes.html', site_name: 'Sudbury Basin', production_t: 12.1, unit_cost: 7800, _status: 'auto', _source_page: undefined },
];
