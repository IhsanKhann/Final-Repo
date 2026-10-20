import type {
  Batch, Mapping, ReviewQueueItem, Insights, HealthStatus,
  SchemaPack, HomeStats, MappingPatchPayload, MappingPatchResponse,
  BulkAcceptPayload, BulkAcceptResponse, CreateBatchPayload,
  PaginatedResponse, DatasetRecord,
  SettingsView, SettingsPatch, ControlView, SecretView,
} from './types';
import { ENDPOINTS } from './endpoints';

// Mock responses were removed once every route served real data. A switchable mock
// is a way to demo fabricated numbers by accident: the UI looks healthy either way.

// ─── Helper ─────────────────────────────────────────────────────────────────

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
  return apiFetch<HomeStats>(ENDPOINTS.home.stats());
}

// ─── Batches ─────────────────────────────────────────────────────────────────
export async function getBatches(): Promise<Batch[]> {
  return apiFetch<Batch[]>(ENDPOINTS.batches.list());
}

export async function getBatch(id: string): Promise<Batch> {
  return apiFetch<Batch>(ENDPOINTS.batches.get(id));
}

export async function createBatch(
  payload: CreateBatchPayload,
  files: File[],
  onProgress?: (pct: number) => void,
): Promise<Batch> {
  const form = new FormData();
  form.append('pack_id', payload.pack_id);
  if (payload.url) form.append('url', payload.url);
  files.forEach(f => form.append('files', f));
  return apiFetch<Batch>(ENDPOINTS.batches.create(), {
    method: 'POST', body: form, headers: {},
  });
}

export async function cancelBatch(id: string): Promise<void> {
  await apiFetch<void>(ENDPOINTS.batches.cancel(id), { method: 'POST' });
}

export async function getBatchRecords(
  id: string, page = 1, perPage = 50,
): Promise<PaginatedResponse<DatasetRecord>> {
  return apiFetch<PaginatedResponse<DatasetRecord>>(ENDPOINTS.batches.records(id, page, perPage));
}

// ─── Documents ───────────────────────────────────────────────────────────────
export async function getDocumentMappings(docId: string): Promise<Mapping[]> {
  return apiFetch<Mapping[]>(ENDPOINTS.documents.mappings(docId));
}

// ─── Mappings ─────────────────────────────────────────────────────────────────
export async function patchMapping(
  id: string, payload: MappingPatchPayload,
): Promise<MappingPatchResponse> {
  return apiFetch<MappingPatchResponse>(ENDPOINTS.mappings.patch(id), {
    method: 'PATCH', body: JSON.stringify(payload),
  });
}

export async function bulkAcceptMappings(payload: BulkAcceptPayload): Promise<BulkAcceptResponse> {
  return apiFetch<BulkAcceptResponse>(ENDPOINTS.mappings.bulkAccept(), {
    method: 'POST', body: JSON.stringify(payload),
  });
}

// ─── Review Queue ─────────────────────────────────────────────────────────────
export async function getReviewQueue(): Promise<ReviewQueueItem[]> {
  return apiFetch<ReviewQueueItem[]>(ENDPOINTS.reviewQueue.list());
}

// ─── Schema Packs ─────────────────────────────────────────────────────────────
export async function getPacks(): Promise<SchemaPack[]> {
  return apiFetch<SchemaPack[]>(ENDPOINTS.packs.list());
}

export async function getPack(id: string): Promise<SchemaPack> {
  return apiFetch<SchemaPack>(ENDPOINTS.packs.get(id));
}

export async function updatePack(id: string, pack: Partial<SchemaPack>): Promise<SchemaPack> {
  return apiFetch<SchemaPack>(ENDPOINTS.packs.update(id), {
    method: 'PUT', body: JSON.stringify(pack),
  });
}

// ─── Insights ─────────────────────────────────────────────────────────────────
export async function getInsights(): Promise<Insights> {
  return apiFetch<Insights>(ENDPOINTS.insights.get());
}

// ─── Health ───────────────────────────────────────────────────────────────────
export async function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>(ENDPOINTS.health.get());
}

// ─── Settings (config layer) ─────────────────────────────────────────────────
// Mirrors `backend/api/settings.py`. The control and secret lists used to be mirrored
// here as mock constants; they are gone because the Settings page's whole purpose is
// showing where each value RESOLVED FROM, and a hardcoded list reporting everything as
// `default` is the one answer that cannot be wrong on screen while being wrong in fact.

export async function getSettings(): Promise<SettingsView> {
  return apiFetch<SettingsView>(ENDPOINTS.settings.get());
}

export async function patchSettings(patch: SettingsPatch): Promise<SettingsView> {
  return apiFetch<SettingsView>(ENDPOINTS.settings.update(), {
    method: 'PATCH', body: JSON.stringify(patch),
  });
}

// ─── SSE Events (real backend only, mock uses a generator) ───────────────────
export function connectBatchEvents(
  batchId: string,
  onEvent: (e: import('./types').AgentEvent) => void,
  onError?: (err: Event) => void,
): EventSource | (() => void) {
  const es = new EventSource(ENDPOINTS.batches.events(batchId));
  es.onmessage = e => {
    try { onEvent(JSON.parse(e.data)); } catch { /* ignore parse errors */ }
  };
  if (onError) es.onerror = onError;
  return es;
}
