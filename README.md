# DataSync — Autonomous Document Standardization & Schema Mapping Agent

DataSync is an enterprise-grade document extraction, normalization, and canonical schema mapping web application. It transforms heterogeneous, messy PDFs, spreadsheets, and web reports into standardized, audit-ready dataset records using Google Gemini AI, Document AI layout analysis, and deterministic unit conversion math.

---

## Key Capabilities

1. **Autonomous 5-Stage Multi-Agent Pipeline**:
   - **Ingestion Agent**: MIME validation, SHA-256 fingerprinting, multi-sheet Excel / HTML table parsing.
   - **OCR & Layout Agent (Document AI)**: Spatial coordinate extraction and bounding box positioning.
   - **Mapping Agent (Gemini 1.5)**: Semantic synonym vector matching with statistical confidence scoring.
   - **Normalization Agent**: Deterministic physical unit conversions (e.g. `lb` &rarr; `t`, `$/lb` &rarr; `$/t`, currency scaling).
   - **Rule Validation Agent**: Range assertions, non-negative checks, and anomaly detection.

2. **Split-Screen Human-in-the-Loop Review**:
   - Interactive document provenance viewer with glowing bounding box and cell coordinate overlays.
   - Rapid keyboard hotkey triage (`A` Accept, `R` Reject, `E` Inline Edit, `↑ / ↓` Navigate).
   - One-click bulk approval for high-confidence predictions (&ge; 90%).
   - Reversible actions with live Undo Bar notifications.

3. **Continuous AI Learning**:
   - Records human corrections into an active memory store.
   - Dynamically adapts synonym vectors and mapping rules for future extraction runs.
   - Visual accuracy and manual effort progression analytics.

4. **Canonical Data Warehouse & Audit Trail**:
   - Standardized tabular view with provenance page/cell links.
   - One-click export to **CSV**, **JSON**, and **SOC-2 / GxP traceable Audit Trail** with validation hashes.

5. **Configurable Schema Packs**:
   - Out-of-the-box domain packs: **Mining v1**, **Shipping v1**, **Finance v1**.
   - Manage target fields, required statuses, synonyms, unit factors, and business rules.

---

## Project Structure

```
Final-Repo/
├── Frontend/
│   ├── src/
│   │   ├── api/             # API client, endpoints, mock data, and TypeScript types
│   │   ├── components/      # Layout (AppShell) and UI components (Badges, Overlays, Skeletons)
│   │   ├── context/         # AppContext (Toast, Undo, Active Schema Pack)
│   │   ├── pages/           # Home, Upload, Batches, Review, Dataset, Schema, Insights, Health, Settings, Help
│   │   ├── index.css        # Full design system (Tokens, Dark mode, Components, Animations)
│   │   ├── App.tsx          # React Router setup & provider nesting
│   │   └── main.tsx         # Application entry point with TanStack Query
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── README.md
```

---

## Quick Start

### Prerequisites
- Node.js 18+
- npm 9+

### Running Locally

```bash
# 1. Navigate to Frontend
cd Frontend

# 2. Install dependencies
npm install

# 3. Start development server
npm run dev
```

The application will be running at **http://localhost:5173/**.

---

## Standalone Demo Mode
By default, `VITE_USE_MOCK=true` is enabled in `Frontend/.env`, allowing the application to demonstrate end-to-end ingestion, SSE agent streaming, live PDF/sheet bounding box inspection, and continuous learning without external cloud credentials.