// ─── All endpoint paths in one place ───────────────────────────────────────
// Backend contract may still change — update here only.

const BASE = import.meta.env.VITE_API_URL ?? '';

export const ENDPOINTS = {
  // Batches
  batches: {
    list: () => `${BASE}/api/batches`,
    create: () => `${BASE}/api/batches`,
    get: (id: string) => `${BASE}/api/batches/${id}`,
    events: (id: string) => `${BASE}/api/batches/${id}/events`,
    cancel: (id: string) => `${BASE}/api/batches/${id}/cancel`,
    records: (id: string, page = 1, perPage = 50) =>
      `${BASE}/api/batches/${id}/records?page=${page}&per_page=${perPage}`,
    export: (id: string, format: 'csv' | 'json', audit: boolean) =>
      `${BASE}/api/batches/${id}/export?format=${format}&audit=${audit}`,
  },

  // Documents
  documents: {
    get: (id: string) => `${BASE}/api/documents/${id}`,
    mappings: (id: string) => `${BASE}/api/documents/${id}/mappings`,
  },

  // Mappings
  mappings: {
    patch: (id: string) => `${BASE}/api/mappings/${id}`,
    bulkAccept: () => `${BASE}/api/mappings/bulk-accept`,
  },

  // Review queue
  reviewQueue: {
    list: () => `${BASE}/api/review-queue`,
  },

  // Schema packs
  packs: {
    list: () => `${BASE}/api/packs`,
    get: (id: string) => `${BASE}/api/packs/${id}`,
    update: (id: string) => `${BASE}/api/packs/${id}`,
  },

  // Insights
  insights: {
    get: () => `${BASE}/api/insights`,
  },

  // Health
  health: {
    get: () => `${BASE}/api/health`,
  },

  // Settings — the config layer. GET returns every resolved value WITH its source;
  // PATCH routes controls and secrets to their two deliberately different resolvers.
  settings: {
    get: () => `${BASE}/api/settings`,
    update: () => `${BASE}/api/settings`,
  },

  // Home stats
  home: {
    stats: () => `${BASE}/api/home/stats`,
  },
} as const;
