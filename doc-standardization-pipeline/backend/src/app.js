require('dotenv').config();
const express = require('express');
const cors = require('cors');
const multer = require('multer');
const { Storage } = require('@google-cloud/storage');
const { BigQuery } = require('@google-cloud/bigquery');

const { extractDocumentText } = require('./services/documentAiService');
const { agenticNormalize } = require('./services/openaiService');

const app = express();
const upload = multer({ limits: { fileSize: 50 * 1024 * 1024 } }); // 50MB limit

app.use(cors());
app.use(express.json({ limit: '50mb' }));

// GCP Config
const GCP_PROJECT_ID = process.env.GCP_PROJECT_ID || process.env.GOOGLE_CLOUD_PROJECT || 'doc-standardization-pipeline';
const SOURCE_BUCKET_NAME = process.env.SOURCE_BUCKET_NAME || '';
const DESTINATION_BUCKET_NAME = process.env.DESTINATION_BUCKET_NAME || '';
const BIGQUERY_DATASET_ID = process.env.BIGQUERY_DATASET_ID || 'doc_standardization_pipeline';
const BIGQUERY_NORMALIZED_TABLE = process.env.BIGQUERY_NORMALIZED_TABLE || 'normalized_records';
const BIGQUERY_REVIEW_TABLE = process.env.BIGQUERY_REVIEW_TABLE || 'review_queue';
const PORT = process.env.PORT || 8080;

let storageClient = null;
let bqClient = null;

function getStorage() {
  if (!storageClient) {
    storageClient = new Storage({ projectId: GCP_PROJECT_ID });
  }
  return storageClient;
}

function getBigQuery() {
  if (!bqClient) {
    bqClient = new BigQuery({ projectId: GCP_PROJECT_ID });
  }
  return bqClient;
}

// In-memory fallback review store for local testing/offline dashboard interaction
let localReviewQueue = [
  {
    id: "rq-001",
    document_id: "ps06_sample_rate_sheets.csv",
    source_file: "ps06_sample_rate_sheets.csv",
    source_bucket: "docai-source-documents",
    document_type: "rate_sheet",
    document_date: "2026-04-12",
    field_name: "fuel_surcharge_calculation",
    raw_value: "14.5% (?) fluctuating",
    standardized_value: "0.145",
    unit: "percentage",
    confidence: 0.62,
    requires_human_review: true,
    reasoning: "Ambiguous notation '(?) fluctuating' in raw document. Analyst verification requested.",
    processed_at: new Date().toISOString(),
    status: "pending_review"
  },
  {
    id: "rq-002",
    document_id: "ps01_documents_metadata.csv",
    source_file: "ps01_documents_metadata.csv",
    source_bucket: "docai-source-documents",
    document_type: "metadata_record",
    document_date: "2026-03-30",
    field_name: "gross_weight",
    raw_value: "2200 lbs/ton metric?",
    standardized_value: "997.9",
    unit: "kg",
    confidence: 0.71,
    requires_human_review: true,
    reasoning: "Conflicting unit notation between US Short Ton and Metric Ton. Human confirmation needed.",
    processed_at: new Date().toISOString(),
    status: "pending_review"
  }
];

// -----------------------------------------------------------------------------
// Health Check (Step 1)
// -----------------------------------------------------------------------------
app.get('/api/health', (req, res) => {
  res.status(200).json({
    status: 'ok',
    service: 'doc-standardization-pipeline-backend',
    timestamp: new Date().toISOString(),
    min_instances_enforced: 0
  });
});

// Root fallback for GCP Cloud Run default ping
app.get('/', (req, res) => {
  res.status(200).json({
    status: 'Agentic Pipeline scaffold ready',
    healthEndpoint: '/api/health'
  });
});

// -----------------------------------------------------------------------------
// Step 2 & 3: Temporary Test Extract Endpoint (/api/test-extract)
// -----------------------------------------------------------------------------
app.post('/api/test-extract', upload.single('file'), async (req, res) => {
  try {
    let fileBuffer;
    let mimeType = 'text/plain';

    if (req.file) {
      fileBuffer = req.file.buffer;
      mimeType = req.file.mimetype || 'application/pdf';
    } else if (req.body && req.body.raw_text) {
      fileBuffer = Buffer.from(req.body.raw_text, 'utf-8');
      mimeType = 'text/plain';
    } else {
      // Default dummy invoice for fast testing
      const dummyText = `
INVOICE #INV-2026-8801
Date: 04/18/2026
Vendor: Apex Logistics Global Inc.
Client: Pacific Maritime Logistics
Item: Intermodal Container Transport (40ft High Cube) - 3 units @ $1,800.00 each -> $5,400.00
Fuel Surcharge: variable rate 12.5% (?)
Total Gross Weight: 38,500 lbs
Tax: $432.00
Total Due: $6,507.00 USD
      `.trim();
      fileBuffer = Buffer.from(dummyText, 'utf-8');
    }

    console.log('[TestExtract] Ingesting document buffer for extraction...');
    let extractionResult;

    if (process.env.DOCAI_PROCESSOR_ID) {
      try {
        extractionResult = await extractDocumentText(fileBuffer, mimeType);
      } catch (docAiErr) {
        console.warn(`[TestExtract] Document AI failed (${docAiErr.message}). Using buffer text.`);
        extractionResult = {
          rawText: fileBuffer.toString('utf-8'),
          routingDecision: 'Synchronous (Simulated Fallback)',
          rateLimitRetries: 0,
          pageCount: 1
        };
      }
    } else {
      extractionResult = {
        rawText: fileBuffer.toString('utf-8'),
        routingDecision: 'Synchronous (Local Mock)',
        rateLimitRetries: 0,
        pageCount: 1
      };
    }

    // Print raw extracted text as required
    console.log('\n================== [RAW EXTRACTED TEXT] ==================');
    console.log(extractionResult.rawText);
    console.log('==========================================================\n');

    // Step 3: Chain into OpenAI agentic normalization
    const normalizedJson = await agenticNormalize(extractionResult.rawText);

    const flaggedCount = (normalizedJson.fields || []).filter(f => f.requires_human_review).length;

    const structuredLog = {
      event: 'test_extraction_completed',
      routing_decision: extractionResult.routingDecision,
      rate_limit_retries: extractionResult.rateLimitRetries,
      fields_flagged_for_review: flaggedCount,
      timestamp: new Date().toISOString()
    };
    console.log(`[STRUCTURED_LOG] ${JSON.stringify(structuredLog)}`);

    res.status(200).json({
      status: 'success',
      routing_decision: extractionResult.routingDecision,
      rate_limit_retries: extractionResult.rateLimitRetries,
      fields_flagged_for_review: flaggedCount,
      raw_text: extractionResult.rawText,
      normalized_data: normalizedJson,
      structured_log: structuredLog
    });
  } catch (err) {
    console.error(`[TestExtract] Error: ${err.message}`);
    res.status(500).json({ error: err.message });
  }
});

// -----------------------------------------------------------------------------
// Step 4: Eventarc Hook & End-to-End Ingestion Pipeline (/api/eventarc-hook)
// -----------------------------------------------------------------------------
app.post('/api/eventarc-hook', async (req, res) => {
  console.log('[EventarcHook] Received push event from Eventarc.');

  try {
    const body = req.body || {};
    let sourceBucket = null;
    let fileName = null;

    // Parse CloudEvents body
    if (body.bucket && body.name) {
      sourceBucket = body.bucket;
      fileName = body.name;
    } else if (body.data && typeof body.data === 'object') {
      sourceBucket = body.data.bucket;
      fileName = body.data.name;
    }

    // Fallback to CloudEvents headers
    if (!fileName && req.headers['ce-subject']) {
      fileName = req.headers['ce-subject'].replace(/^objects\//, '');
    }

    if (!sourceBucket || !fileName) {
      console.error('[EventarcHook] Missing source bucket or file name in payload:', body);
      return res.status(400).json({ error: 'Invalid Eventarc payload: missing bucket or name' });
    }

    console.log(`[EventarcHook] Ingesting gs://${sourceBucket}/${fileName}`);

    // Download file from GCS
    const sClient = getStorage();
    const bucket = sClient.bucket(sourceBucket);
    const file = bucket.file(fileName);

    const [exists] = await file.exists();
    if (!exists) {
      return res.status(404).json({ error: `File gs://${sourceBucket}/${fileName} not found` });
    }

    const [fileBuffer] = await file.download();
    const [metadata] = await file.getMetadata();
    const mimeType = metadata.contentType || 'application/pdf';
    const gcsSourceUri = `gs://${sourceBucket}/${fileName}`;

    // Step 2: Extract text via Document AI
    const { rawText, routingDecision, rateLimitRetries, pageCount } = await extractDocumentText(
      fileBuffer,
      mimeType,
      gcsSourceUri,
      sourceBucket
    );

    // Step 3: Agentic normalization via OpenAI GPT-4o
    const normalizedJson = await agenticNormalize(rawText);

    // Step 4: Upload normalized JSON to destination GCS bucket
    const destBucketName = DESTINATION_BUCKET_NAME || sourceBucket;
    const destBucket = sClient.bucket(destBucketName);
    const baseName = fileName.replace(/\.[^/.]+$/, '');
    const destFileName = `normalized/${baseName}_normalized.json`;
    const destFile = destBucket.file(destFileName);

    await destFile.save(JSON.stringify(normalizedJson, null, 2), {
      contentType: 'application/json'
    });
    const gcsOutputUri = `gs://${destBucketName}/${destFileName}`;
    console.log(`[EventarcHook] Uploaded normalized JSON to ${gcsOutputUri}`);

    // Step 5: BigQuery Streaming Export & Human Review Routing
    const { highConfidenceCount, flaggedCount } = await streamToBigQuery({
      normalizedJson,
      fileName,
      sourceBucket,
      routingDecision,
      rateLimitRetries
    });

    // Step 5: Structured Logging
    const structuredLog = {
      event: 'document_processed',
      file_name: fileName,
      bucket: sourceBucket,
      routing_decision: routingDecision,
      rate_limit_retries: rateLimitRetries,
      fields_flagged_for_review: flaggedCount,
      high_confidence_records: highConfidenceCount,
      gcs_output_uri: gcsOutputUri,
      page_count: pageCount,
      timestamp: new Date().toISOString()
    };
    console.log(`[STRUCTURED_LOG] ${JSON.stringify(structuredLog)}`);

    res.status(200).json({
      status: 'success',
      gcs_output_uri: gcsOutputUri,
      structured_log: structuredLog
    });
  } catch (err) {
    console.error(`[EventarcHook] Fatal processing error: ${err.message}`, err);
    res.status(500).json({ error: err.message });
  }
});

// -----------------------------------------------------------------------------
// Step 5: BigQuery Streaming Helper
// -----------------------------------------------------------------------------
async function streamToBigQuery({ normalizedJson, fileName, sourceBucket, routingDecision, rateLimitRetries }) {
  const bq = getBigQuery();
  const fields = normalizedJson.fields || [];
  const docId = normalizedJson.document_identifier || fileName;
  const docType = normalizedJson.document_type || 'unclassified';
  const docDate = normalizedJson.document_date || null;
  const now = new Date().toISOString();

  const highConfidenceRows = [];
  const reviewQueueRows = [];

  for (const f of fields) {
    const row = {
      document_id: docId,
      source_file: fileName,
      source_bucket: sourceBucket,
      document_type: docType,
      document_date: docDate,
      field_name: f.field_name,
      raw_value: String(f.raw_value || ''),
      standardized_value: String(f.standardized_value || ''),
      unit: f.unit || null,
      confidence: parseFloat(f.confidence || 0.0),
      requires_human_review: Boolean(f.requires_human_review),
      reasoning: f.reasoning || '',
      processed_at: now,
      routing_decision: routingDecision,
      rate_limit_retries: rateLimitRetries
    };

    if (f.requires_human_review === true || f.confidence < 0.85) {
      reviewQueueRows.push(row);
      // Also cache in local review queue for frontend analyst UI
      localReviewQueue.unshift({
        id: `rq-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
        ...row,
        status: 'pending_review'
      });
    } else {
      highConfidenceRows.push(row);
    }
  }

  try {
    const dataset = bq.dataset(BIGQUERY_DATASET_ID);
    if (highConfidenceRows.length > 0) {
      await dataset.table(BIGQUERY_NORMALIZED_TABLE).insert(highConfidenceRows, { raw: true });
      console.log(`[BigQuery] Streamed ${highConfidenceRows.length} rows to ${BIGQUERY_NORMALIZED_TABLE}`);
    }
    if (reviewQueueRows.length > 0) {
      await dataset.table(BIGQUERY_REVIEW_TABLE).insert(reviewQueueRows, { raw: true });
      console.log(`[BigQuery] Streamed ${reviewQueueRows.length} rows to ${BIGQUERY_REVIEW_TABLE} (Review Queue)`);
    }
  } catch (bqErr) {
    console.warn(`[BigQuery] Streaming insert skipped or failed (GCP credentials/tables): ${bqErr.message}`);
  }

  return {
    highConfidenceCount: highConfidenceRows.length,
    flaggedCount: reviewQueueRows.length
  };
}

// -----------------------------------------------------------------------------
// Frontend API Routes (Review Queue, Manual Correction Feedback Loop, Upload)
// -----------------------------------------------------------------------------
app.get('/api/review-queue', async (req, res) => {
  // Attempt to read from BigQuery review_queue table if credentials present
  try {
    if (process.env.GCP_PROJECT_ID && process.env.BIGQUERY_DATASET_ID) {
      const bq = getBigQuery();
      const query = `
        SELECT * FROM \`${GCP_PROJECT_ID}.${BIGQUERY_DATASET_ID}.${BIGQUERY_REVIEW_TABLE}\`
        WHERE requires_human_review = TRUE
        ORDER BY processed_at DESC
        LIMIT 50
      `;
      const [rows] = await bq.query({ query });
      if (rows && rows.length > 0) {
        return res.status(200).json({ records: rows });
      }
    }
  } catch (err) {
    console.warn(`[ReviewQueueAPI] BigQuery query failed: ${err.message}. Serving local review queue.`);
  }

  res.status(200).json({ records: localReviewQueue });
});

// Human-in-the-loop analyst feedback approval endpoint
app.post('/api/review-queue/:id/approve', async (req, res) => {
  const { id } = req.params;
  const { corrected_value, corrected_unit, analyst_notes } = req.body;

  const itemIndex = localReviewQueue.findIndex(item => item.id === id);
  if (itemIndex === -1) {
    return res.status(404).json({ error: 'Review item not found' });
  }

  const item = localReviewQueue[itemIndex];
  item.standardized_value = corrected_value !== undefined ? String(corrected_value) : item.standardized_value;
  item.unit = corrected_unit !== undefined ? corrected_unit : item.unit;
  item.requires_human_review = false;
  item.confidence = 1.0;
  item.reasoning = `[Analyst Corrected & Approved]: ${analyst_notes || 'Confirmed valid'}`;
  item.status = 'approved';

  // Stream approved corrected record into BigQuery normalized_records
  try {
    const bq = getBigQuery();
    await bq.dataset(BIGQUERY_DATASET_ID).table(BIGQUERY_NORMALIZED_TABLE).insert([
      {
        document_id: item.document_id,
        source_file: item.source_file,
        source_bucket: item.source_bucket,
        document_type: item.document_type,
        document_date: item.document_date,
        field_name: item.field_name,
        raw_value: item.raw_value,
        standardized_value: item.standardized_value,
        unit: item.unit,
        confidence: 1.0,
        requires_human_review: false,
        reasoning: item.reasoning,
        processed_at: new Date().toISOString(),
        routing_decision: item.routing_decision || 'Manual Approval',
        rate_limit_retries: item.rate_limit_retries || 0
      }
    ]);
    console.log(`[FeedbackLoop] Approved record successfully appended to BigQuery ${BIGQUERY_NORMALIZED_TABLE}`);
  } catch (err) {
    console.warn(`[FeedbackLoop] Note: BigQuery insert for approved row skipped/failed: ${err.message}`);
  }

  res.status(200).json({
    message: 'Record approved and written to normalized production table.',
    record: item
  });
});

// Direct upload from React frontend
app.post('/api/upload', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No file provided in form-data' });
    }

    const fileName = req.file.originalname || `upload_${Date.now()}.pdf`;
    const mimeType = req.file.mimetype || 'application/pdf';
    const targetBucketName = SOURCE_BUCKET_NAME || DESTINATION_BUCKET_NAME || 'docai-source-documents';

    // If GCP bucket configured, upload directly to source bucket to trigger Eventarc
    if (SOURCE_BUCKET_NAME) {
      const sClient = getStorage();
      const bucket = sClient.bucket(targetBucketName);
      const file = bucket.file(fileName);
      await file.save(req.file.buffer, { contentType: mimeType });
      console.log(`[UploadAPI] Saved file to gs://${targetBucketName}/${fileName}`);
    }

    // Also run immediate extraction & agentic normalization pipeline
    let extractionResult;
    try {
      extractionResult = await extractDocumentText(req.file.buffer, mimeType);
    } catch (docAiErr) {
      console.warn(`[UploadAPI] DocAI call note: ${docAiErr.message}. Falling back to text parser.`);
      extractionResult = {
        rawText: req.file.buffer.toString('utf-8'),
        routingDecision: 'Synchronous',
        rateLimitRetries: 0,
        pageCount: 1
      };
    }

    const normalizedJson = await agenticNormalize(extractionResult.rawText);

    // Stream to BigQuery / Review Queue
    await streamToBigQuery({
      normalizedJson,
      fileName,
      sourceBucket: targetBucketName,
      routingDecision: extractionResult.routingDecision,
      rateLimitRetries: extractionResult.rateLimitRetries
    });

    res.status(200).json({
      message: 'File ingested and processed successfully',
      file_name: fileName,
      routing_decision: extractionResult.routingDecision,
      normalized_data: normalizedJson
    });
  } catch (err) {
    console.error(`[UploadAPI] Error: ${err.message}`);
    res.status(500).json({ error: err.message });
  }
});

// Mock sample references endpoint
app.get('/api/mock-samples', (req, res) => {
  res.status(200).json({
    samples: [
      {
        id: 'ps01',
        filename: 'ps01_documents_metadata.csv',
        description: 'Multi-document ingestion catalog with legacy metadata tags and timestamps.',
        content_preview: 'doc_id,creation_date,facility,gross_weight,status\nDOC-991,03/30/2026,Facility-West,2200 lbs/ton metric?,FLAGGED'
      },
      {
        id: 'ps06',
        filename: 'ps06_sample_rate_sheets.csv',
        description: 'Intermodal freight contract rate sheets with regional fuel surcharges.',
        content_preview: 'lane_id,origin,dest,base_freight_rate,fuel_surcharge\nLANE-401,Chicago,Seattle,$1450.00 / load,14.5% (?) fluctuating'
      }
    ]
  });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`[Server] Document Standardization Backend running on port ${PORT}`);
});

module.exports = app;
