# Backend image for Cloud Run.
#
# Built from the REPO ROOT, not from backend/, because the package is imported as
# `backend.api.main` and the pack loader resolves `data/samples/` relative to the repo
# root. Build with:  gcloud builds submit --config backend/cloudbuild.yaml .
#
# No credential is baked in and none is passed as an env var — AGREEMENTS §1. The
# service gets CONFIG_STORE=firestore and resolves its key from the store, which is why
# a redeploy does not lose it.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libraries pdfplumber/PyMuPDF need at runtime. Kept minimal on purpose: every
# extra package is cold-start latency on a min-instances=0 service.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first so the layer caches across code changes.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
 && pip install --no-cache-dir google-cloud-firestore google-cloud-storage google-cloud-bigquery

COPY backend/ /app/backend/
COPY data/ /app/data/

# Cloud Run sets $PORT and may change it; never hardcode 8080.
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1
