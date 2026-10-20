# Document Standardization Pipeline

Enterprise full-stack document processing pipeline on Google Cloud Platform with React (Vite + Tailwind CSS), Node.js Express, Google Cloud Document AI, Eventarc, Cloud Run, OpenAI GPT-4o, and Google Cloud BigQuery.

## Project Structure

```
doc-standardization-pipeline/
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   └── provider.tf
├── backend/
│   ├── src/
│   │   ├── app.js
│   │   └── services/
│   │       ├── documentAiService.js
│   │       └── openaiService.js
│   ├── package.json
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   └── ReviewQueue.jsx
│   │   └── index.css
│   ├── public/
│   │   └── image_b9f2e2.png
│   ├── package.json
│   └── vite.config.js
├── image_b9f2e2.png
├── .env.example
└── README.md
```

For full setup instructions, deployment commands, architecture diagrams, and testing, see [doc-standardization-pipeline/README.md](file:///d:/Final-Repo/doc-standardization-pipeline/README.md).