import type {
  Batch, Mapping, ReviewQueueItem, Insights, HealthStatus,
  SchemaPack, HomeStats, MappingPatchPayload, MappingPatchResponse,
  BulkAcceptPayload, BulkAcceptResponse, CreateBatchPayload,
  PaginatedResponse, DatasetRecord,
} from './types';
import { ENDPOINTS } from './endpoints';
import {
  MOCK_BATCHES, MOCK_MAPPINGS, MOCK_REVIEW_QUEUE, MOCK_INSIGHTS,
  MOCK_HEALTH, MOCK_HOME_STATS, MOCK_PACKS, MOCK_RECORDS,
} from './mockData';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

// ─── Helper ─────────────────────────────────────────────────────────────────
const delay = (ms: number) => new Promise(r => setTimeout(r, ms));

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new ApiError(res.status, text || res.statusText, url);
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public url: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = 'ApiError';
  }
}

// ─── Home ────────────────────────────────────────────────────────────────────
export async function getHomeStats(): Promise<HomeStats> {
  if (USE_MOCK) { await delay(300); return MOCK_HOME_STATS; }
  return apiFetch<HomeStats>(ENDPOINTS.home.stats());
}

// ─── Batches ─────────────────────────────────────────────────────────────────
export async function getBatches(): Promise<Batch[]> {
  if (USE_MOCK) { await delay(400); return MOCK_BATCHES; }
  return apiFetch<Batch[]>(ENDPOINTS.batches.list());
}

export async function getBatch(id: string): Promise<Batch> {
  if (USE_MOCK) {
    await delay(200);
    const b = MOCK_BATCHES.find(x => x.id === id);
    if (!b) throw new ApiError(404, 'Batch not found', id);
    return b;
  }
  return apiFetch<Batch>(ENDPOINTS.batches.get(id));
}

export async function createBatch(
  payload: CreateBatchPayload,
  files: File[],
  onProgress?: (pct: number) => void,
): Promise<Batch> {
  if (USE_MOCK) {
    // Simulate upload progress
    for (let p = 0; p <= 100; p += 20) { onProgress?.(p); await delay(200); }
    const mock: Batch = {
      id: `batch-${Date.now()}`,
      name: `Batch ${new Date().toLocaleTimeString()}`,
      pack_id: payload.pack_id,
      pack_name: MOCK_PACKS.find(p => p.id === payload.pack_id)?.name ?? payload.pack_id,
      files: files.map((f, i) => ({
        id: `f-${i}`, name: f.name, type: f.type, size: f.size,
        status: 'ready', progress: 0,
      })),
      stage: 'ingesting', status: 'running',
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    MOCK_BATCHES.unshift(mock);
    return mock;
  }
  const form = new FormData();
  form.append('pack_id', payload.pack_id);
  if (payload.url) form.append('url', payload.url);
  files.forEach(f => form.append('files', f));
  return apiFetch<Batch>(ENDPOINTS.batches.create(), {
    method: 'POST', body: form, headers: {},
  });
}

export async function cancelBatch(id: string): Promise<void> {
  if (USE_MOCK) { await delay(200); return; }
  await apiFetch<void>(ENDPOINTS.batches.cancel(id), { method: 'POST' });
}

export async function retryBatchFile(batchId: string, fileId: string): Promise<void> {
  if (USE_MOCK) { await delay(200); return; }
  await apiFetch<void>(ENDPOINTS.batches.retryFile(batchId, fileId), { method: 'POST' });
}

export async function retryBatchStep(batchId: string, step: string): Promise<void> {
  if (USE_MOCK) { await delay(200); return; }
  await apiFetch<void>(ENDPOINTS.batches.retryStep(batchId, step), { method: 'POST' });
}

export async function getBatchRecords(
  id: string, page = 1, perPage = 50,
): Promise<PaginatedResponse<DatasetRecord>> {
  if (USE_MOCK) {
    await delay(300);
    return { data: MOCK_RECORDS, total: MOCK_RECORDS.length, page, per_page: perPage };
  }
  return apiFetch<PaginatedResponse<DatasetRecord>>(ENDPOINTS.batches.records(id, page, perPage));
}

// ─── Documents ───────────────────────────────────────────────────────────────
export async function getDocumentMappings(docId: string): Promise<Mapping[]> {
  if (USE_MOCK) {
    await delay(400);
    const maps = MOCK_MAPPINGS.filter(m => m.document_id === docId);
    if (!maps.length) {
      if (docId === 'doc-error') throw new ApiError(503, 'AI service unavailable', docId);
    }
    return maps;
  }
  try {
    const maps = await apiFetch<Mapping[]>(ENDPOINTS.documents.mappings(docId));
    if (maps && maps.length > 0) return maps;
  } catch (err) {
    console.warn(`[getDocumentMappings] Backend call failed for ${docId}, falling back to sample mappings:`, err);
  }
  return MOCK_MAPPINGS.filter(m => m.document_id === docId);
}

// ─── Mappings ─────────────────────────────────────────────────────────────────
export async function patchMapping(
  id: string, payload: MappingPatchPayload,
): Promise<MappingPatchResponse> {
  if (USE_MOCK) {
    await delay(250);
    const m = MOCK_MAPPINGS.find(x => x.id === id);
    if (!m) throw new ApiError(404, 'Mapping not found', id);
    const updated = { ...m, status: payload.action === 'accept' ? 'approved' as const : payload.action === 'reject' ? 'rejected' as const : m.status };
    if (payload.value) updated.value = payload.value;
    if (payload.unit) updated.unit = payload.unit;
    Object.assign(m, updated);
    const learned = Math.random() > 0.5;
    return { mapping: updated, learned, learned_message: learned ? `Learned: "${m.source_label}" → "${m.target_field}" mapping updated` : undefined };
  }
  return apiFetch<MappingPatchResponse>(ENDPOINTS.mappings.patch(id), {
    method: 'PATCH', body: JSON.stringify(payload),
  });
}

export async function bulkAcceptMappings(payload: BulkAcceptPayload): Promise<BulkAcceptResponse> {
  if (USE_MOCK) {
    await delay(500);
    const maps = MOCK_MAPPINGS.filter(
      m => m.document_id === payload.document_id && m.confidence >= payload.min_confidence,
    );
    maps.forEach(m => { m.status = 'approved'; });
    return { accepted_count: maps.length, mappings: maps };
  }
  return apiFetch<BulkAcceptResponse>(ENDPOINTS.mappings.bulkAccept(), {
    method: 'POST', body: JSON.stringify(payload),
  });
}

// ─── Review Queue ─────────────────────────────────────────────────────────────
export async function getReviewQueue(): Promise<ReviewQueueItem[]> {
  if (USE_MOCK) { await delay(350); return MOCK_REVIEW_QUEUE; }
  return apiFetch<ReviewQueueItem[]>(ENDPOINTS.reviewQueue.list());
}

// ─── Schema Packs ─────────────────────────────────────────────────────────────
export async function getPacks(): Promise<SchemaPack[]> {
  if (USE_MOCK) { await delay(200); return MOCK_PACKS; }
  return apiFetch<SchemaPack[]>(ENDPOINTS.packs.list());
}

export async function getPack(id: string): Promise<SchemaPack> {
  if (USE_MOCK) {
    await delay(200);
    const p = MOCK_PACKS.find(x => x.id === id);
    if (!p) throw new ApiError(404, 'Pack not found', id);
    return p;
  }
  return apiFetch<SchemaPack>(ENDPOINTS.packs.get(id));
}

export async function updatePack(id: string, pack: Partial<SchemaPack>): Promise<SchemaPack> {
  if (USE_MOCK) {
    await delay(300);
    const idx = MOCK_PACKS.findIndex(x => x.id === id);
    if (idx === -1) throw new ApiError(404, 'Pack not found', id);
    Object.assign(MOCK_PACKS[idx], pack);
    return MOCK_PACKS[idx];
  }
  return apiFetch<SchemaPack>(ENDPOINTS.packs.update(id), {
    method: 'PUT', body: JSON.stringify(pack),
  });
}

// ─── Insights ─────────────────────────────────────────────────────────────────
export async function getInsights(): Promise<Insights> {
  if (USE_MOCK) { await delay(400); return MOCK_INSIGHTS; }
  return apiFetch<Insights>(ENDPOINTS.insights.get());
}

// ─── Health ───────────────────────────────────────────────────────────────────
export async function getHealth(): Promise<HealthStatus> {
  if (USE_MOCK) { await delay(150); return MOCK_HEALTH; }
  return apiFetch<HealthStatus>(ENDPOINTS.health.get());
}

// ─── SSE Events (real backend only, mock uses a generator) ───────────────────
export function connectBatchEvents(
  batchId: string,
  onEvent: (e: import('./types').AgentEvent) => void,
  onError?: (err: Event) => void,
): EventSource | (() => void) {
  if (USE_MOCK) {
    // Simulate SSE stream with mock events
    const steps = [
      { agent: 'Ingestion Agent', step: 'ingest', status: 'running' as const, message: 'Reading uploaded files…' },
      { agent: 'OCR Agent', step: 'parse', status: 'running' as const, message: 'Extracting text with Document AI…' },
      { agent: 'OCR Agent', step: 'parse', status: 'done' as const, message: 'Text extracted from all pages' },
      { agent: 'Mapping Agent', step: 'map', status: 'running' as const, message: 'Identifying fields with Gemini…' },
      { agent: 'Mapping Agent', step: 'map', status: 'done' as const, message: '42 fields identified, 12 need review' },
      { agent: 'Normalization Agent', step: 'normalize', status: 'running' as const, message: 'Applying unit conversions…' },
      { agent: 'Validation Agent', step: 'validate', status: 'done' as const, message: 'All business rules checked. Ready.' },
    ];
    let i = 0;
    const interval = setInterval(() => {
      if (i >= steps.length) { clearInterval(interval); return; }
      onEvent({ id: `evt-${i}`, timestamp: new Date().toISOString(), ...steps[i] });
      i++;
    }, 1200);
    return () => clearInterval(interval);
  }
  const es = new EventSource(ENDPOINTS.batches.events(batchId));
  es.onmessage = e => {
    try { onEvent(JSON.parse(e.data)); } catch { /* ignore parse errors */ }
  };
  if (onError) es.onerror = onError;
  return es;
}
