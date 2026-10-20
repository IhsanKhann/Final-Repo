import type { PipelineEvent, PipelineStepKey } from '../api/types';

export interface SimulatorController {
  stop: () => void;
  retryFile: (fileId: string) => void;
  retryStep: (step: PipelineStepKey) => void;
}

/**
 * Simulates real-time multi-agent execution events following the contract
 * over approximately 30 seconds for 3 files:
 * 1. rates_q3.xlsx (Excel - 1 page, 12 fields)
 * 2. filing.pdf (PDF scan - 9 pages, 24 fields)
 * 3. notes.html (HTML - 4 pages, 6 fields) - experiences a transient failure and retries!
 */
export function startProgressSimulation(
  batchId: string,
  onEvent: (event: PipelineEvent) => void
): SimulatorController {
  const timers: ReturnType<typeof setTimeout>[] = [];
  let isStopped = false;

  const emit = (event: PipelineEvent) => {
    if (isStopped) return;
    onEvent(event);
  };

  const schedule = (ms: number, fn: () => void) => {
    const t = setTimeout(() => {
      if (!isStopped) fn();
    }, ms);
    timers.push(t);
  };

  const now = Date.now();

  // Initial step setup
  schedule(100, () => {
    emit({
      type: 'log',
      agent: 'Orchestrator',
      level: 'info',
      message: 'Batch initialized with 3 heterogeneous documents. Launching multi-agent pipeline.',
      ts: now + 100,
    });

    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'ingest',
      status: 'running',
      done: 0,
      total: 3,
      unit: 'files',
      message: 'Ingesting 3 files: validating MIME signatures and checksums',
      ts: now + 150,
    });

    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-rates',
      file_name: 'rates_q3.xlsx',
      step: 'ingest',
      status: 'running',
      done: 0,
      total: 1,
      unit: 'files',
      ts: now + 180,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-filing',
      file_name: 'filing.pdf',
      step: 'ingest',
      status: 'waiting',
      done: 0,
      total: 1,
      unit: 'files',
      ts: now + 190,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-notes',
      file_name: 'notes.html',
      step: 'ingest',
      status: 'waiting',
      done: 0,
      total: 1,
      unit: 'files',
      ts: now + 200,
    });
  });

  // Ingest file 1
  schedule(1500, () => {
    emit({
      type: 'log',
      agent: 'Ingestion Agent',
      level: 'info',
      message: 'rates_q3.xlsx MIME signature verified (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet).',
      file_id: 'f-rates',
      file_name: 'rates_q3.xlsx',
      ts: now + 1500,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-rates',
      file_name: 'rates_q3.xlsx',
      step: 'ingest',
      status: 'done',
      done: 1,
      total: 1,
      unit: 'files',
      ts: now + 1500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'ingest',
      status: 'running',
      done: 1,
      total: 3,
      unit: 'files',
      message: '1 of 3 files ingested',
      ts: now + 1520,
    });
  });

  // Ingest file 2
  schedule(3000, () => {
    emit({
      type: 'log',
      agent: 'Ingestion Agent',
      level: 'info',
      message: 'filing.pdf validated: 9 pages scanned PDF.',
      file_id: 'f-filing',
      file_name: 'filing.pdf',
      ts: now + 3000,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-filing',
      file_name: 'filing.pdf',
      step: 'ingest',
      status: 'done',
      done: 1,
      total: 1,
      unit: 'files',
      ts: now + 3000,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'ingest',
      status: 'running',
      done: 2,
      total: 3,
      unit: 'files',
      message: '2 of 3 files ingested',
      ts: now + 3020,
    });
  });

  // Ingest file 3 & Complete Ingest Step
  schedule(4500, () => {
    emit({
      type: 'log',
      agent: 'Ingestion Agent',
      level: 'success',
      message: 'notes.html validated: UTF-8 HTML markup with tabular disclosures.',
      file_id: 'f-notes',
      file_name: 'notes.html',
      ts: now + 4500,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-notes',
      file_name: 'notes.html',
      step: 'ingest',
      status: 'done',
      done: 1,
      total: 1,
      unit: 'files',
      ts: now + 4500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'ingest',
      status: 'done',
      done: 3,
      total: 3,
      unit: 'files',
      message: 'Done (3 of 3 files)',
      ts: now + 4520,
    });
  });

  // ─── Step 2: Parse / OCR (Document AI) ───────────────────────────────────
  schedule(5500, () => {
    emit({
      type: 'log',
      agent: 'OCR Agent',
      level: 'info',
      message: 'Invoking Google Cloud Document AI layout parsing across 14 pages...',
      ts: now + 5500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'parse',
      status: 'running',
      done: 0,
      total: 14,
      unit: 'pages',
      message: 'Extracting bounding boxes & tabular text layout',
      ts: now + 5520,
    });
  });

  // Parse rates_q3.xlsx (1 page)
  schedule(7000, () => {
    emit({
      type: 'log',
      agent: 'OCR Agent',
      level: 'info',
      message: 'rates_q3.xlsx: Extracted sheet 1 table coordinates and headers.',
      file_id: 'f-rates',
      file_name: 'rates_q3.xlsx',
      ts: now + 7000,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-rates',
      file_name: 'rates_q3.xlsx',
      step: 'parse',
      status: 'done',
      done: 1,
      total: 1,
      unit: 'pages',
      ts: now + 7000,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'parse',
      status: 'running',
      done: 1,
      total: 14,
      unit: 'pages',
      message: '1 of 14 pages',
      ts: now + 7020,
    });
  });

  // Parse filing.pdf partial (4 pages)
  schedule(8500, () => {
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-filing',
      file_name: 'filing.pdf',
      step: 'parse',
      status: 'running',
      done: 4,
      total: 9,
      unit: 'pages',
      message: 'Processing pages 1-4',
      ts: now + 8500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'parse',
      status: 'running',
      done: 5,
      total: 14,
      unit: 'pages',
      message: '5 of 14 pages (36%)',
      ts: now + 8520,
    });
  });

  // Parse filing.pdf complete (9 pages) -> 10/14 pages total (71%)
  schedule(10500, () => {
    emit({
      type: 'log',
      agent: 'OCR Agent',
      level: 'info',
      message: 'filing.pdf: Document AI extracted 9 pages of multi-column freight disclosures.',
      file_id: 'f-filing',
      file_name: 'filing.pdf',
      ts: now + 10500,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-filing',
      file_name: 'filing.pdf',
      step: 'parse',
      status: 'done',
      done: 9,
      total: 9,
      unit: 'pages',
      ts: now + 10500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'parse',
      status: 'running',
      done: 10,
      total: 14,
      unit: 'pages',
      message: '10 of 14 pages (71%)',
      ts: now + 10520,
    });
  });

  // Parse notes.html encounters transient failure!
  schedule(12000, () => {
    emit({
      type: 'log',
      agent: 'OCR Agent',
      level: 'error',
      message: 'notes.html failed: Parser error: unescaped XML entity on line 42.',
      file_id: 'f-notes',
      file_name: 'notes.html',
      ts: now + 12000,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-notes',
      file_name: 'notes.html',
      step: 'parse',
      status: 'failed',
      done: 0,
      total: 4,
      unit: 'pages',
      message: 'Unescaped entity in table header (Retryable)',
      ts: now + 12000,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'parse',
      status: 'warning',
      done: 10,
      total: 14,
      unit: 'pages',
      message: 'Done with warnings (1 file failed, retry available)',
      ts: now + 12050,
    });
  });

  // Automated retry kicks in for notes.html
  schedule(14000, () => {
    emit({
      type: 'log',
      agent: 'OCR Agent',
      level: 'warn',
      message: 'Retrying notes.html with fault-tolerant DOM sanitization parser...',
      file_id: 'f-notes',
      file_name: 'notes.html',
      ts: now + 14000,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-notes',
      file_name: 'notes.html',
      step: 'parse',
      status: 'running',
      done: 2,
      total: 4,
      unit: 'pages',
      message: 'Sanitizing and parsing HTML nodes',
      ts: now + 14020,
    });
  });

  // notes.html succeeds on retry! Parse step done!
  schedule(16000, () => {
    emit({
      type: 'log',
      agent: 'OCR Agent',
      level: 'success',
      message: 'notes.html: Parsed 4 pages of HTML disclosure tables cleanly.',
      file_id: 'f-notes',
      file_name: 'notes.html',
      ts: now + 16000,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-notes',
      file_name: 'notes.html',
      step: 'parse',
      status: 'done',
      done: 4,
      total: 4,
      unit: 'pages',
      ts: now + 16000,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'parse',
      status: 'done',
      done: 14,
      total: 14,
      unit: 'pages',
      message: 'Done 100% (14 of 14 pages)',
      ts: now + 16050,
    });
  });

  // ─── Step 3: Map Fields (Gemini / GPT-4o Reasoning) ─────────────────────
  schedule(17000, () => {
    emit({
      type: 'log',
      agent: 'Mapping Agent',
      level: 'info',
      message: 'Analyzing semantic entities and canonical schema targets across 42 fields...',
      ts: now + 17000,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'map',
      status: 'running',
      done: 0,
      total: 42,
      unit: 'fields',
      message: 'Extracting canonical fields with confidence scoring',
      ts: now + 17050,
    });
  });

  schedule(18500, () => {
    emit({
      type: 'log',
      agent: 'Mapping Agent',
      level: 'info',
      message: 'rates_q3.xlsx: 12 fields mapped. Base rate and fuel surcharges identified.',
      file_id: 'f-rates',
      file_name: 'rates_q3.xlsx',
      ts: now + 18500,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-rates',
      file_name: 'rates_q3.xlsx',
      step: 'map',
      status: 'done',
      done: 12,
      total: 12,
      unit: 'fields',
      ts: now + 18500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'map',
      status: 'running',
      done: 13,
      total: 42,
      unit: 'fields',
      message: '13 of 42 fields (30%)',
      ts: now + 18550,
    });
  });

  schedule(20000, () => {
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'map',
      status: 'running',
      done: 28,
      total: 42,
      unit: 'fields',
      message: '28 of 42 fields (67%)',
      ts: now + 20000,
    });
  });

  schedule(21500, () => {
    emit({
      type: 'log',
      agent: 'Mapping Agent',
      level: 'warn',
      message: 'filing.pdf & notes.html: 42 fields mapped. 12 fields flagged below 0.85 confidence threshold.',
      ts: now + 21500,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-filing',
      file_name: 'filing.pdf',
      step: 'map',
      status: 'done',
      done: 24,
      total: 24,
      unit: 'fields',
      ts: now + 21500,
    });
    emit({
      type: 'file_progress',
      batch_id: batchId,
      file_id: 'f-notes',
      file_name: 'notes.html',
      step: 'map',
      status: 'done',
      done: 6,
      total: 6,
      unit: 'fields',
      ts: now + 21500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'map',
      status: 'warning',
      done: 42,
      total: 42,
      unit: 'fields',
      flagged: 12,
      message: 'Done with warnings (12 fields need review)',
      ts: now + 21550,
    });
  });

  // ─── Step 4: Normalize (Unit Math) ──────────────────────────────────────
  schedule(23000, () => {
    emit({
      type: 'log',
      agent: 'Normalization Agent',
      level: 'info',
      message: 'Computing deterministic physical unit conversions (lbs -> kg, EUR -> USD)...',
      ts: now + 23000,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'normalize',
      status: 'running',
      done: 0,
      total: 42,
      unit: 'fields',
      message: 'Applying conversion formulas and ISO standardization',
      ts: now + 23050,
    });
  });

  schedule(24500, () => {
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'normalize',
      status: 'running',
      done: 20,
      total: 42,
      unit: 'fields',
      message: '20 of 42 fields (48%)',
      ts: now + 24500,
    });
  });

  schedule(25500, () => {
    emit({
      type: 'log',
      agent: 'Normalization Agent',
      level: 'success',
      message: 'All 42 numerical values converted to canonical units without floating point drift.',
      ts: now + 25500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'normalize',
      status: 'done',
      done: 42,
      total: 42,
      unit: 'fields',
      message: 'Done 100% (42 of 42 fields)',
      ts: now + 25550,
    });
  });

  // ─── Step 5: Validate (Business Rules) ──────────────────────────────────
  schedule(26500, () => {
    emit({
      type: 'log',
      agent: 'Validation Agent',
      level: 'info',
      message: 'Executing range assertions, non-negative checks, and schema validation...',
      ts: now + 26500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'validate',
      status: 'running',
      done: 0,
      total: 3,
      unit: 'records',
      message: 'Validating business constraints across 3 records',
      ts: now + 26550,
    });
  });

  schedule(27500, () => {
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'validate',
      status: 'running',
      done: 2,
      total: 3,
      unit: 'records',
      message: '2 of 3 records',
      ts: now + 27500,
    });
  });

  schedule(28500, () => {
    emit({
      type: 'log',
      agent: 'Validation Agent',
      level: 'success',
      message: 'Business rules checked: 30 auto-approved, 12 routed to Review Queue.',
      ts: now + 28500,
    });
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'validate',
      status: 'done',
      done: 3,
      total: 3,
      unit: 'records',
      message: 'Done 100% (3 of 3 records)',
      ts: now + 28550,
    });
  });

  // ─── Step 6: Ready & Batch Done ─────────────────────────────────────────
  schedule(29500, () => {
    emit({
      type: 'step_progress',
      batch_id: batchId,
      step: 'ready',
      status: 'done',
      done: 3,
      total: 3,
      unit: 'records',
      message: 'Done 100% (Ready for Review)',
      ts: now + 29500,
    });
  });

  schedule(30000, () => {
    emit({
      type: 'batch_done',
      batch_id: batchId,
      summary: {
        fields: 42,
        flagged: 12,
        auto_approved: 30,
      },
      ts: now + 30000,
    });

    emit({
      type: 'log',
      agent: 'Orchestrator',
      level: 'success',
      message: 'Batch standardization completed successfully. 42 fields identified, 12 need review.',
      ts: now + 30050,
    });
  });

  return {
    stop: () => {
      isStopped = true;
      timers.forEach(t => clearTimeout(t));
    },
    retryFile: (fileId: string) => {
      emit({
        type: 'log',
        agent: 'Orchestrator',
        level: 'info',
        message: `Manual retry initiated for ${fileId}...`,
        file_id: fileId,
        ts: Date.now(),
      });
      emit({
        type: 'file_progress',
        batch_id: batchId,
        file_id: fileId,
        file_name: fileId,
        step: 'parse',
        status: 'running',
        done: 2,
        total: 4,
        unit: 'pages',
        message: 'Re-running parser',
        ts: Date.now(),
      });
      setTimeout(() => {
        emit({
          type: 'file_progress',
          batch_id: batchId,
          file_id: fileId,
          file_name: fileId,
          step: 'parse',
          status: 'done',
          done: 4,
          total: 4,
          unit: 'pages',
          ts: Date.now(),
        });
      }, 1500);
    },
    retryStep: (step: PipelineStepKey) => {
      emit({
        type: 'log',
        agent: 'Orchestrator',
        level: 'info',
        message: `Manual retry initiated for step ${step}...`,
        ts: Date.now(),
      });
      emit({
        type: 'step_progress',
        batch_id: batchId,
        step,
        status: 'running',
        done: 0,
        total: 10,
        unit: 'fields',
        run_id: `retry-${Date.now()}`,
        message: 'Re-executing step',
        ts: Date.now(),
      });
    },
  };
}
