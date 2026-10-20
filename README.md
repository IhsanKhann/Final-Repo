# Document Standardization & Schema Mapping Systems

This repository contains two enterprise document intelligence solutions:

1. **Document Standardization Pipeline (`doc-standardization-pipeline/`)**: Event-driven GCP architecture using Document AI, Eventarc, Cloud Run (`min-instances=0`), OpenAI GPT-4o, and BigQuery with a React + Node.js analyst review portal.
2. **DataSync (`Frontend/`)**: Autonomous 5-stage document standardization and canonical schema mapping agent application.

---

## 📁 Repository Structure

```
Final-Repo/
├── doc-standardization-pipeline/   # GCP Document AI + Eventarc + OpenAI + BigQuery Pipeline
│   ├── terraform/                   # Terraform IaC (GCS, DocAI, Cloud Run, Eventarc, BigQuery)
│   ├── backend/                     # Node.js Express Backend
│   ├── frontend/                    # React (Vite + Tailwind) Analyst Dashboard
│   ├── image_b9f2e2.png             # Architecture Diagram Asset
│   ├── .env.example
│   └── README.md
├── Frontend/                        # DataSync React + TypeScript Client
│   ├── src/
│   ├── package.json
│   └── README.md
├── .gitignore
└── README.md
```

---

## 1. Document Standardization Pipeline (`doc-standardization-pipeline/`)

An event-driven document processing system on Google Cloud Platform:
- **GCS & Eventarc**: Ingestion triggers Cloud Run automatically.
- **Document AI**: Pre-processes page counts; automatically switches to async batch processing for $>15$ pages, with HTTP 429 exponential backoff retries.
- **OpenAI GPT-4o Agent**: Performs unit conversions, structured JSON normalization, and ambiguity confidence scoring (`requires_human_review`).
- **BigQuery Feedback Loop**: High-confidence records stream to `normalized_records`, while flagged items stream to `review_queue` for analyst correction.
- **Local Dashboard**: Runs at [http://localhost:3000](http://localhost:3000) (Backend at [http://localhost:8080](http://localhost:8080)).

For full deployment and operational details, see [`doc-standardization-pipeline/README.md`](file:///d:/Final-Repo/doc-standardization-pipeline/README.md).

---

## 2. DataSync Client (`Frontend/`)

Autonomous document standardization with split-screen provenance and bounding box review.

```bash
cd Frontend
npm install
npm run dev
```
Runs at [http://localhost:5173](http://localhost:5173).
