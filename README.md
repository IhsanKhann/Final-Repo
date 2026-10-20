# Enterprise Document Standardization & Schema Mapping Platform

A streamlined enterprise document processing and canonical schema mapping platform.

---

## 🏛️ Architecture & Components

```
Final-Repo/
├── Frontend/                        # Unified React + TypeScript Application (Vite on port 5173)
│   ├── src/
│   │   ├── api/                     # Backend API client, endpoints, and mock fallback
│   │   ├── components/              # Provenance viewer, overlays, and shell
│   │   ├── pages/                   # Batches, Review, Upload, Schema, Insights, Dataset, Health
│   │   ├── App.tsx                  # Router & navigation
│   │   └── main.tsx
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts               # Proxies /api to Node.js backend (port 8080)
├── doc-standardization-pipeline/
│   ├── backend/                     # Node.js Express Backend (port 8080)
│   │   ├── src/
│   │   │   ├── app.js               # Eventarc hook, BigQuery streaming, Review Queue API
│   │   │   └── services/
│   │   │       ├── documentAiService.js  # Doc AI extraction, >15 page batch routing, HTTP 429 backoff
│   │   │       └── openaiService.js      # GPT-4o agentic mapping, unit conversions, ambiguity scoring
│   │   ├── package.json
│   │   └── Dockerfile               # Container for Cloud Run (min-instances=0)
│   ├── terraform/                   # Infrastructure as Code
│   │   ├── main.tf                  # Provisions GCS buckets, SA, Doc AI, Cloud Run, Eventarc, BigQuery
│   │   ├── variables.tf
│   │   └── provider.tf
│   ├── .env.example
│   └── README.md
├── .gitignore
└── README.md
```

---

## 🚀 Running Locally

### 1. Start the Node.js Backend
```bash
cd doc-standardization-pipeline/backend
npm install
npm start
```
> Running on **http://localhost:8080**  
> Health check: `http://localhost:8080/api/health`

### 2. Start the Frontend
```bash
cd Frontend
npm install
npm run dev
```
> Running on **http://localhost:5173**  
> Automatically proxies `/api` requests to the Node.js backend.
