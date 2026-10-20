# DataSync Frontend Architecture (PS-12)

This document describes the architectural design, component hierarchy, and API integration for the **DataSync: Cross-Source Data Standardization & Transformation Agent** frontend application.

---

## 1. Architectural Philosophy

- **Domain-Agnostic Design**: Target schemas are never hardcoded in UI components. All field definitions, units, synonyms, and validation rules are derived dynamically from the active **Schema Pack** (`mining-v1`, `shipping-v1`, `finance-v1`).
- **Nielsen's 10 Heuristics Compliant**: Status visibility, user control (universal Undo), error prevention, recognizability over recall, and clear error recovery.
- **Rossum-Style Split Screen**: Side-by-side inspection pairing source document coordinates (bounding boxes & spreadsheet cells) with extracted canonical mappings.
- **Fail-Safe API Layer**: All endpoint URLs are isolated in `src/api/endpoints.ts` and all data contracts in `src/api/types.ts`. The UI gracefully handles missing fields, schema changes, and service disruptions.

---

## 2. Component Hierarchy & Flow

```
[AppRoot (src/main.tsx)]
  └── QueryClientProvider (TanStack Query)
        └── ToastProvider (Universal feedback alerts)
              └── UndoProvider (Reversible user actions)
                    └── PackProvider (Active schema state)
                          └── BrowserRouter (React Router)
                                └── AppShell
                                      ├── SidebarNav (Workspace, Configure, Footer)
                                      ├── Header (Schema selector, Search, Status chip, Avatar)
                                      ├── Main Content (Route matching)
                                      │     ├── /           -> HomePage
                                      │     ├── /upload     -> UploadPage (Dropzone & Live Run)
                                      │     ├── /batches    -> BatchesPage
                                      │     ├── /review     -> ReviewPage (Split View + Detail Drawer)
                                      │     ├── /review-queue -> ReviewQueuePage (Global Queue)
                                      │     ├── /dataset    -> DatasetPage
                                      │     ├── /schema     -> SchemaPage
                                      │     ├── /insights   -> InsightsPage
                                      │     ├── /health     -> HealthPage
                                      │     └── /settings   -> SettingsPage
                                      ├── MobileBottomNav
                                      ├── ToastContainer
                                      └── UndoBar
```

---

## 3. Screen Breakdown & API Interactions

### Screen 1: Home Dashboard (`HomePage.tsx`)
- **API Call**: `GET /api/home/stats`
- **Functionality**:
  - 4 core metrics: Documents Ingested, Auto-Approved %, Pending Human Review, AI Extraction Accuracy (+delta).
  - Multi-Agent pipeline architecture stepper.
  - Recent batches table with stage & resolution metrics.

### Screen 2 & 3: Upload & Live Run (`UploadPage.tsx`)
- **API Calls**:
  - `GET /api/packs`
  - `POST /api/batches` (multipart form with files or URL)
  - `GET /api/batches/{id}/events` (Server-Sent Events)
  - `POST /api/batches/{id}/cancel`
- **Functionality**:
  - Multi-file drag & drop supporting PDF, XLSX, CSV, HTML, TXT with file type validation.
  - Unsupported file alerts with immediate removal option.
  - 6-stage pipeline progress stepper: Ingest &rarr; Parse/OCR &rarr; Map fields &rarr; Normalize &rarr; Validate &rarr; Ready.
  - Real-time SSE Agent Activity terminal stream.

### Screen 4 & 5: Mapping Review & Record Detail Drawer (`ReviewPage.tsx`)
- **API Calls**:
  - `GET /api/documents/{id}/mappings`
  - `PATCH /api/mappings/{id}` (`{ action: 'accept' | 'reject' | 'edit', value, unit, reason }`)
  - `POST /api/mappings/bulk-accept` (`{ document_id, min_confidence }`)
- **Functionality**:
  - **Rossum Split Screen**: Left pane renders PDF bounding boxes or Excel sheet cell highlights based on `source_location`.
  - **Proposed Mappings**: Sorted with *Needs Review* and *Missing* items at the top.
  - **Record Detail Drawer (Screen 5)**: Opens on edit, displaying confidence assessment, plain-language explanation of why it was flagged, unit conversion formula breakdown, validation pass/fail assertions, editable canonical value/unit, and analyst rationale textarea.
  - **Continuous Learning**: When a correction is saved, the model records the rule into memory vectors and displays a toast with an Undo action.
  - **Keyboard Hotkeys**: `J/K` or `↓/↑` navigate items, `A` accept, `E` open detail drawer, `R` reject, `Z` undo, `/` focus search.

### Screen 6: Review Queue (`ReviewQueuePage.tsx`)
- **API Call**: `GET /api/review-queue`
- **Functionality**:
  - Aggregates all flagged fields across all documents, sorted by lowest confidence first.
  - Multi-select controls and "Open First (Enter)" quick triage.

### Screen 7: Canonical Dataset & Export (`DatasetPage.tsx`)
- **API Calls**:
  - `GET /api/batches/{id}/records`
  - `GET /api/batches/{id}/export?format=csv|json&audit=true|false`
- **Functionality**:
  - Tabular data warehouse with column visibility toggles and search.
  - Source location chips linking directly back to the document viewer coordinates.
  - Unresolved flags warning banner: "7 fields still need review [Review now] [Export anyway]".
  - Download CSV and JSON with checkbox to toggle regulatory audit trail metadata.

### Screen 8: Schema & Rules Manager (`SchemaPage.tsx`)
- **API Calls**:
  - `GET /api/packs`
  - `PUT /api/packs/{id}`
- **Functionality**:
  - Schema Pack management across industry domains.
  - Target fields and synonym vector vocabulary editor.
  - Unit normalization multiplier rules.
  - Business sanity constraints.

### Screen 9: Insights & Feedback Loop (`InsightsPage.tsx`)
- **API Call**: `GET /api/insights`
- **Functionality**:
  - Four key performance metrics: Mapping Accuracy, Conversion Correctness, Manual Effort Saved, Feedback Improvement.
  - Recharts progression chart across batch iterations.
  - Knowledge base of rules learned from human corrections.

---

## 4. Design System & Heuristics Compliance

| Heuristic | Implementation in DataSync |
| :--- | :--- |
| **1. Visibility of Status** | Steppers on Upload & Live Run; per-file progress bars; live "Saved just now" timestamps; system status chip in header. |
| **2. Real-World Match** | Plain-language labels ("Needs your review"), extracted raw units shown alongside canonical targets. |
| **3. User Control & Freedom** | Persistent Undo Bar on every accept, edit, or reject; cancelable pipeline runs; "Restore Raw Source Value" button. |
| **4. Consistency** | Universal status vocabulary: Auto-approved (green check), Needs review (amber), Missing/Invalid (red), Approved by you (blue check), Processing (spinner). |
| **5. Error Prevention** | File format and size validation on drop; warning modal before export if unreviewed fields remain; no automatic acceptance for low-confidence predictions. |
| **6. Recognition over Recall** | Extracted source values displayed adjacent to proposed canonical mappings; spatial bounding box pins on document canvas. |
| **7. Efficiency of Use** | Bulk accept (&ge; 90% confidence); rapid keyboard shortcuts (`J`, `K`, `A`, `E`, `R`, `Z`, `/`). |
| **8. Aesthetic & Minimal Design** | Clean Rossum-inspired light theme; details isolated inside side drawers when requested; single primary CTA per screen. |
| **9. Error Recovery** | Informative error banners with retry triggers; resilient offline mock mode for zero downtime during demos. |
| **10. Help & Documentation** | Tooltips on confidence scores; complete platform guide in `/help`; keyboard shortcut cheat-sheet. |

---

## 5. Google Cloud Run Deployment

The application is containerized with a multi-stage Docker build:
1. **Builder Stage**: `node:20-alpine` installs dependencies and compiles the Vite production bundle (`npm run build`).
2. **Runtime Stage**: `nginx:alpine` dynamically replaces `$PORT` from Google Cloud Run into `nginx.conf` and serves the static assets with Gzip compression and long-term caching.
