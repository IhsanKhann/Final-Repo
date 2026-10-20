const { DocumentProcessorServiceClient } = require('@google-cloud/documentai').v1;
const { Storage } = require('@google-cloud/storage');
const { PDFDocument } = require('pdf-lib');

const GCP_PROJECT_ID = process.env.GCP_PROJECT_ID || process.env.GOOGLE_CLOUD_PROJECT || 'doc-standardization-pipeline';
const GCP_LOCATION = process.env.GCP_LOCATION || 'us';
const DOCAI_PROCESSOR_ID = process.env.DOCAI_PROCESSOR_ID || '';
const DESTINATION_BUCKET_NAME = process.env.DESTINATION_BUCKET_NAME || '';

// Initialize clients lazily or safely
let docAiClient = null;
let storageClient = null;

function getDocAiClient() {
  if (!docAiClient) {
    const apiEndpoint = `${GCP_LOCATION}-documentai.googleapis.com`;
    docAiClient = new DocumentProcessorServiceClient({ apiEndpoint });
  }
  return docAiClient;
}

function getStorageClient() {
  if (!storageClient) {
    storageClient = new Storage({ projectId: GCP_PROJECT_ID });
  }
  return storageClient;
}

/**
 * Pre-processing validation: Inspects document buffer to compute page count.
 * Multi-format support: PDF page count via pdf-lib with regex fallback, 1 page for others.
 */
async function getDocumentPageCount(fileBuffer, mimeType = 'application/pdf') {
  if (mimeType.toLowerCase().includes('pdf')) {
    try {
      const pdfDoc = await PDFDocument.load(fileBuffer, { ignoreEncryption: true });
      const count = pdfDoc.getPageCount();
      console.log(`[DocumentAIService] PDF pre-processing parsed ${count} page(s).`);
      return count;
    } catch (err) {
      console.warn(`[DocumentAIService] pdf-lib failed to parse page count: ${err.message}. Checking regex fallback.`);
      const matches = fileBuffer.toString('binary').match(/\/Type\s*\/Page\b/g);
      if (matches && matches.length > 0) {
        return matches.length;
      }
    }
  }
  // For HTML, spreadsheets (CSV, XLSX), images, default to 1 page
  return 1;
}

/**
 * Extracts document text using Google Cloud Document AI.
 * 
 * Rules:
 *  - Pre-processing: If page count > 15, routes to async batch processing (batchProcessDocuments).
 *  - If page count <= 15, routes to synchronous processDocument.
 *  - HTTP 429 Rate Limit Handling: Exponential backoff with jitter.
 * 
 * Returns: { rawText, routingDecision, rateLimitRetries, pageCount }
 */
async function extractDocumentText(fileBuffer, mimeType = 'application/pdf', gcsSourceUri = null, stagingBucket = null) {
  const client = getDocAiClient();
  const processorName = client.processorPath(GCP_PROJECT_ID, GCP_LOCATION, DOCAI_PROCESSOR_ID);
  const pageCount = await getDocumentPageCount(fileBuffer, mimeType);

  const maxRetries = 5;
  const baseBackoffMs = 1500;
  let rateLimitRetries = 0;
  let routingDecision = 'Synchronous';
  let rawText = '';

  if (pageCount > 15) {
    routingDecision = 'Async Batch';
    console.log(`[DocumentAIService] Page count is ${pageCount} (>15 rule). Routing to Document AI batchProcessDocuments.`);

    const sClient = getStorageClient();
    let stagingUri = gcsSourceUri;

    // If file is not in GCS, stage it for batch processing
    if (!stagingUri) {
      const targetBucket = stagingBucket || DESTINATION_BUCKET_NAME || 'docai-staging-bucket';
      const tempPath = `staging/batch_${Date.now()}_${Math.floor(Math.random() * 10000)}.pdf`;
      const bucket = sClient.bucket(targetBucket);
      const file = bucket.file(tempPath);
      await file.save(fileBuffer, { contentType: mimeType });
      stagingUri = `gs://${targetBucket}/${tempPath}`;
      console.log(`[DocumentAIService] Staged file buffer to GCS for batch processing: ${stagingUri}`);
    }

    const outputBucket = DESTINATION_BUCKET_NAME || stagingBucket || 'docai-normalized-outputs';
    const outputPrefix = `batch_output/${Date.now()}/`;
    const gcsOutputUri = `gs://${outputBucket}/${outputPrefix}`;

    const batchRequest = {
      name: processorName,
      inputDocuments: {
        gcsDocuments: {
          documents: [
            {
              gcsUri: stagingUri,
              mimeType: mimeType
            }
          ]
        }
      },
      documentOutputConfig: {
        gcsOutputConfig: {
          gcsUri: gcsOutputUri
        }
      }
    };

    // Exponential backoff loop for batch process initiation
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        console.log(`[DocumentAIService] Initiating batchProcessDocuments (Attempt ${attempt + 1}/${maxRetries})...`);
        const [operation] = await client.batchProcessDocuments(batchRequest);
        console.log(`[DocumentAIService] Async batch operation started. Waiting for completion...`);
        await operation.promise();
        console.log(`[DocumentAIService] Async batch processing operation completed successfully.`);
        break;
      } catch (err) {
        const isRateLimit = err.code === 8 || err.code === 429 || (err.message && err.message.includes('429'));
        if (isRateLimit) {
          rateLimitRetries++;
          if (attempt === maxRetries - 1) throw err;
          const waitTime = baseBackoffMs * Math.pow(2, attempt) + Math.random() * 500;
          console.warn(`[DocumentAIService] HTTP 429 Rate Limit encountered. Retrying in ${Math.round(waitTime)}ms...`);
          await new Promise((resolve) => setTimeout(resolve, waitTime));
        } else {
          throw err;
        }
      }
    }

    // Retrieve and aggregate output text from GCS
    rawText = await retrieveBatchOutputText(outputBucket, outputPrefix);

  } else {
    routingDecision = 'Synchronous';
    console.log(`[DocumentAIService] Page count is ${pageCount} (<=15 rule). Routing to Document AI processDocument.`);

    const requestPayload = {
      name: processorName,
      rawDocument: {
        content: fileBuffer.toString('base64'),
        mimeType: mimeType
      }
    };

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        console.log(`[DocumentAIService] Calling processDocument (Attempt ${attempt + 1}/${maxRetries})...`);
        const [result] = await client.processDocument(requestPayload);
        rawText = result.document?.text || '';
        console.log(`[DocumentAIService] Synchronous extraction succeeded. Extracted ${rawText.length} characters.`);
        break;
      } catch (err) {
        const isRateLimit = err.code === 8 || err.code === 429 || (err.message && err.message.includes('429'));
        if (isRateLimit) {
          rateLimitRetries++;
          if (attempt === maxRetries - 1) throw err;
          const waitTime = baseBackoffMs * Math.pow(2, attempt) + Math.random() * 500;
          console.warn(`[DocumentAIService] HTTP 429 Rate Limit encountered. Retrying in ${Math.round(waitTime)}ms...`);
          await new Promise((resolve) => setTimeout(resolve, waitTime));
        } else {
          throw err;
        }
      }
    }
  }

  return {
    rawText,
    routingDecision,
    rateLimitRetries,
    pageCount
  };
}

/**
 * Downloads generated JSON files from GCS after async batch processing.
 */
async function retrieveBatchOutputText(bucketName, prefix) {
  const sClient = getStorageClient();
  const bucket = sClient.bucket(bucketName);
  const [files] = await bucket.getFiles({ prefix });

  const textSnippets = [];
  for (const file of files) {
    if (file.name.endsWith('.json')) {
      const [contents] = await file.download();
      const parsed = JSON.parse(contents.toString('utf8'));
      if (parsed.text) {
        textSnippets.push(parsed.text);
      }
    }
  }
  return textSnippets.join('\n');
}

module.exports = {
  extractDocumentText,
  getDocumentPageCount
};
