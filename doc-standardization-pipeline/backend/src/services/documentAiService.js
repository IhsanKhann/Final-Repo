const { DocumentProcessorServiceClient } = require('@google-cloud/documentai').v1;
const { Storage } = require('@google-cloud/storage');
const { PDFDocument } = require('pdf-lib');
const pdfParse = require('pdf-parse');
const XLSX = require('xlsx');

const GCP_PROJECT_ID = process.env.GCP_PROJECT_ID || process.env.GOOGLE_CLOUD_PROJECT || 'doc-standardization-pipeline';
const GCP_LOCATION = process.env.GCP_LOCATION || 'us';
const DOCAI_PROCESSOR_ID = process.env.DOCAI_PROCESSOR_ID || '';
const DESTINATION_BUCKET_NAME = process.env.DESTINATION_BUCKET_NAME || '';

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
 * Pre-processing validation: Computes document page count.
 */
async function getDocumentPageCount(fileBuffer, mimeType = 'application/pdf') {
  if (mimeType.toLowerCase().includes('pdf')) {
    try {
      const pdfDoc = await PDFDocument.load(fileBuffer, { ignoreEncryption: true });
      const count = pdfDoc.getPageCount();
      return count;
    } catch (err) {
      const matches = fileBuffer.toString('binary').match(/\/Type\s*\/Page\b/g);
      if (matches && matches.length > 0) return matches.length;
    }
  }
  return 1;
}

/**
 * Native, zero-cloud fallback extractor for multi-format documents (PDF, Excel, CSV, HTML, TXT).
 * Guarantees 100% uptime even when GCP credentials or credits are missing.
 */
async function extractDocumentTextNative(fileBuffer, mimeType = 'application/pdf') {
  const mime = mimeType.toLowerCase();

  // 1. PDF Documents
  if (mime.includes('pdf')) {
    try {
      const parsed = await pdfParse(fileBuffer);
      console.log(`[NativeExtractor] Extracted ${parsed.numpages} PDF page(s) and ${parsed.text.length} characters.`);
      return {
        text: parsed.text || '',
        pages: parsed.numpages || 1
      };
    } catch (err) {
      console.warn(`[NativeExtractor] pdf-parse failed: ${err.message}. Using binary string stream.`);
      return { text: fileBuffer.toString('utf-8'), pages: 1 };
    }
  }

  // 2. Excel & Spreadsheets (.xlsx, .xls)
  if (mime.includes('spreadsheet') || mime.includes('excel') || mime.includes('sheet') || mime.includes('xls')) {
    try {
      const workbook = XLSX.read(fileBuffer, { type: 'buffer' });
      const sheetTexts = [];
      for (const sheetName of workbook.SheetNames) {
        const sheet = workbook.Sheets[sheetName];
        const csvText = XLSX.utils.sheet_to_csv(sheet);
        sheetTexts.push(`--- Sheet: ${sheetName} ---\n${csvText}`);
      }
      const aggregated = sheetTexts.join('\n\n');
      console.log(`[NativeExtractor] Parsed ${workbook.SheetNames.length} Excel sheet(s).`);
      return { text: aggregated, pages: workbook.SheetNames.length };
    } catch (err) {
      console.warn(`[NativeExtractor] XLSX parsing failed: ${err.message}.`);
      return { text: fileBuffer.toString('utf-8'), pages: 1 };
    }
  }

  // 3. CSV, HTML, TXT, and plain formats
  return {
    text: fileBuffer.toString('utf-8'),
    pages: 1
  };
}

/**
 * Extracts document text with automated fallback:
 * 1. Checks page count (>15 page rule).
 * 2. If GCP Document AI is configured, uses Document AI with HTTP 429 exponential backoff retries.
 * 3. If GCP is unconfigured or returns authentication/quota errors, seamlessly switches to NativeExtractor.
 */
async function extractDocumentText(fileBuffer, mimeType = 'application/pdf', gcsSourceUri = null, stagingBucket = null) {
  const pageCount = await getDocumentPageCount(fileBuffer, mimeType);
  let routingDecision = pageCount > 15 ? 'Async Batch (>15p)' : 'Synchronous (<=15p)';
  let rateLimitRetries = 0;
  let rawText = '';

  // Attempt Google Cloud Document AI if processor ID is provided
  if (DOCAI_PROCESSOR_ID && process.env.GOOGLE_APPLICATION_CREDENTIALS) {
    try {
      const client = getDocAiClient();
      const processorName = client.processorPath(GCP_PROJECT_ID, GCP_LOCATION, DOCAI_PROCESSOR_ID);
      const maxRetries = 5;
      const baseBackoffMs = 1500;

      if (pageCount > 15) {
        routingDecision = 'Async Batch (Doc AI)';
        const sClient = getStorageClient();
        let stagingUri = gcsSourceUri;
        if (!stagingUri) {
          const targetBucket = stagingBucket || DESTINATION_BUCKET_NAME || 'docai-staging-bucket';
          const tempPath = `staging/batch_${Date.now()}_${Math.floor(Math.random() * 10000)}.pdf`;
          const bucket = sClient.bucket(targetBucket);
          const file = bucket.file(tempPath);
          await file.save(fileBuffer, { contentType: mimeType });
          stagingUri = `gs://${targetBucket}/${tempPath}`;
        }

        const outputBucket = DESTINATION_BUCKET_NAME || stagingBucket || 'docai-normalized-outputs';
        const outputPrefix = `batch_output/${Date.now()}/`;
        const gcsOutputUri = `gs://${outputBucket}/${outputPrefix}`;

        const batchRequest = {
          name: processorName,
          inputDocuments: { gcsDocuments: { documents: [{ gcsUri: stagingUri, mimeType }] } },
          documentOutputConfig: { gcsOutputConfig: { gcsUri: gcsOutputUri } }
        };

        for (let attempt = 0; attempt < maxRetries; attempt++) {
          try {
            const [operation] = await client.batchProcessDocuments(batchRequest);
            await operation.promise();
            break;
          } catch (err) {
            const isRateLimit = err.code === 8 || err.code === 429 || (err.message && err.message.includes('429'));
            if (isRateLimit) {
              rateLimitRetries++;
              if (attempt === maxRetries - 1) throw err;
              const waitTime = baseBackoffMs * Math.pow(2, attempt) + Math.random() * 500;
              await new Promise(r => setTimeout(r, waitTime));
            } else {
              throw err;
            }
          }
        }
        rawText = await retrieveBatchOutputText(outputBucket, outputPrefix);

      } else {
        routingDecision = 'Synchronous (Doc AI)';
        const requestPayload = {
          name: processorName,
          rawDocument: {
            content: fileBuffer.toString('base64'),
            mimeType: mimeType
          }
        };

        for (let attempt = 0; attempt < maxRetries; attempt++) {
          try {
            const [result] = await client.processDocument(requestPayload);
            rawText = result.document?.text || '';
            break;
          } catch (err) {
            const isRateLimit = err.code === 8 || err.code === 429 || (err.message && err.message.includes('429'));
            if (isRateLimit) {
              rateLimitRetries++;
              if (attempt === maxRetries - 1) throw err;
              const waitTime = baseBackoffMs * Math.pow(2, attempt) + Math.random() * 500;
              await new Promise(r => setTimeout(r, waitTime));
            } else {
              throw err;
            }
          }
        }
      }
    } catch (gcpErr) {
      console.warn(`[DocumentAIService] GCP call failed (${gcpErr.message}). Falling back to NativeExtractor.`);
      const nativeResult = await extractDocumentTextNative(fileBuffer, mimeType);
      rawText = nativeResult.text;
      routingDecision = pageCount > 15 ? 'Async Batch (Local Engine)' : 'Synchronous (Local Engine)';
    }
  } else {
    // Zero-cloud fallback: extracts PDF, Excel, CSV, HTML with native parsers
    const nativeResult = await extractDocumentTextNative(fileBuffer, mimeType);
    rawText = nativeResult.text;
    routingDecision = pageCount > 15 ? 'Async Batch (Local Engine)' : 'Synchronous (Local Engine)';
  }

  return {
    rawText,
    routingDecision,
    rateLimitRetries,
    pageCount
  };
}

async function retrieveBatchOutputText(bucketName, prefix) {
  const sClient = getStorageClient();
  const bucket = sClient.bucket(bucketName);
  const [files] = await bucket.getFiles({ prefix });
  const textSnippets = [];
  for (const file of files) {
    if (file.name.endsWith('.json')) {
      const [contents] = await file.download();
      const parsed = JSON.parse(contents.toString('utf8'));
      if (parsed.text) textSnippets.push(parsed.text);
    }
  }
  return textSnippets.join('\n');
}

module.exports = {
  extractDocumentText,
  extractDocumentTextNative,
  getDocumentPageCount
};
