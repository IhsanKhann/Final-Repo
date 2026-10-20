import type {
  PipelineStepKey,
  StepStatus,
  ProgressUnit,
  StepProgressEvent,
  FileProgressEvent,
  LogEvent,
  BatchDoneEvent,
  BatchErrorEvent,
  PipelineEvent,
} from '../api/types';

export const PIPELINE_STEPS: Array<{
  key: PipelineStepKey;
  stepNumber: number;
  name: string;
  sublabel: string;
  defaultUnit: ProgressUnit;
}> = [
  { key: 'ingest', stepNumber: 1, name: 'Ingest', sublabel: 'MIME validation', defaultUnit: 'files' },
  { key: 'parse', stepNumber: 2, name: 'Parse / OCR', sublabel: 'Document AI layout', defaultUnit: 'pages' },
  { key: 'map', stepNumber: 3, name: 'Map fields', sublabel: 'Gemini reasoning', defaultUnit: 'fields' },
  { key: 'normalize', stepNumber: 4, name: 'Normalize', sublabel: 'Unit math', defaultUnit: 'fields' },
  { key: 'validate', stepNumber: 5, name: 'Validate', sublabel: 'Business rules', defaultUnit: 'records' },
  { key: 'ready', stepNumber: 6, name: 'Ready', sublabel: 'Human review', defaultUnit: 'records' },
];

export interface StepProgressState {
  step: PipelineStepKey;
  stepNumber: number;
  name: string;
  sublabel: string;
  status: StepStatus;
  done: number;
  total: number | null;
  unit: ProgressUnit;
  percent: number | null; // null = indeterminate
  isIndeterminate: boolean;
  message?: string;
  flagged?: number;
  runId?: string;
  lastTs: number;
}

export interface FileStepProgress {
  step: PipelineStepKey;
  status: 'waiting' | 'running' | 'done' | 'warning' | 'failed' | 'cancelled';
  done: number;
  total: number | null;
  unit: ProgressUnit;
  percent: number | null;
}

export interface FileProgressState {
  file_id: string;
  file_name: string;
  step: PipelineStepKey;
  status: 'waiting' | 'running' | 'done' | 'warning' | 'failed' | 'cancelled';
  done: number;
  total: number | null;
  unit: ProgressUnit;
  message?: string;
  steps: Record<PipelineStepKey, FileStepProgress>;
  lastTs: number;
}

export interface ThroughputSample {
  ts: number;
  percent: number;
}

export interface BatchProgressState {
  batchId: string;
  status: 'waiting' | 'running' | 'done' | 'warning' | 'failed' | 'cancelled';
  steps: Record<PipelineStepKey, StepProgressState>;
  files: Record<string, FileProgressState>;
  logs: LogEvent[];
  overallPercent: number | null; // null if indeterminate
  isOverallIndeterminate: boolean;
  filesProcessed: number;
  totalFiles: number;
  startTime: number | null;
  endTime: number | null;
  elapsedSeconds: number;
  etaSeconds: number | null;
  throughputSamples: ThroughputSample[];
  completedSummary?: { fields: number; flagged: number; auto_approved?: number };
  activeFileIdHighlight: string | null;
  milestoneAnnouncement: string | null;
  alertError: string | null;
}

export function computeStepPercent(done: number, total: number | null, status: StepStatus): {
  percent: number | null;
  isIndeterminate: boolean;
} {
  if (status === 'done') {
    return { percent: 100, isIndeterminate: false };
  }
  if (total === null || total <= 0) {
    return {
      percent: null,
      isIndeterminate: status === 'running',
    };
  }
  const pct = Math.min(100, Math.max(0, Math.round((done / total) * 100)));
  return { percent: pct, isIndeterminate: false };
}

export function computeOverallProgress(steps: Record<PipelineStepKey, StepProgressState>): {
  overallPercent: number | null;
  isOverallIndeterminate: boolean;
} {
  let knownCount = 0;
  let sumPercent = 0;
  let allDone = true;

  for (const def of PIPELINE_STEPS) {
    const s = steps[def.key];
    if (!s) continue;

    if (s.status !== 'done') {
      allDone = false;
    }

    if (s.status === 'done') {
      knownCount++;
      sumPercent += 100;
    } else if (s.total !== null && s.total > 0) {
      knownCount++;
      const p = Math.min(100, Math.max(0, (s.done / s.total) * 100));
      sumPercent += p;
    }
  }

  if (allDone) {
    return { overallPercent: 100, isOverallIndeterminate: false };
  }

  if (knownCount === 0) {
    return { overallPercent: null, isOverallIndeterminate: true };
  }

  // Mean of the step percentages (unknown totals excluded from average)
  const avg = Math.min(100, Math.max(0, Math.round(sumPercent / knownCount)));
  return { overallPercent: avg, isOverallIndeterminate: false };
}

export function computeEta(
  samples: ThroughputSample[],
  currentPercent: number | null
): number | null {
  if (currentPercent === null || currentPercent >= 100) return null;
  if (samples.length < 3) return null;

  // Use the first and last sample to compute throughput rate (% per second)
  const first = samples[0];
  const last = samples[samples.length - 1];
  const deltaTsSec = (last.ts - first.ts) / 1000;
  const deltaPct = last.percent - first.percent;

  if (deltaTsSec <= 0 || deltaPct <= 0) return null;

  const ratePerSec = deltaPct / deltaTsSec;
  if (ratePerSec <= 0) return null;

  const remainingPct = 100 - currentPercent;
  const etaSec = Math.round(remainingPct / ratePerSec);
  return etaSec > 0 && etaSec < 86400 ? etaSec : null;
}

export function createInitialFileStepProgress(step: PipelineStepKey, unit: ProgressUnit): FileStepProgress {
  return {
    step,
    status: 'waiting',
    done: 0,
    total: null,
    unit,
    percent: null,
  };
}

export function createInitialStepState(key: PipelineStepKey): StepProgressState {
  const def = PIPELINE_STEPS.find(s => s.key === key)!;
  return {
    step: key,
    stepNumber: def.stepNumber,
    name: def.name,
    sublabel: def.sublabel,
    status: 'waiting',
    done: 0,
    total: null,
    unit: def.defaultUnit,
    percent: null,
    isIndeterminate: false,
    lastTs: 0,
  };
}

export function createInitialBatchProgressState(batchId: string): BatchProgressState {
  const steps = {} as Record<PipelineStepKey, StepProgressState>;
  for (const def of PIPELINE_STEPS) {
    steps[def.key] = createInitialStepState(def.key);
  }

  return {
    batchId,
    status: 'waiting',
    steps,
    files: {},
    logs: [],
    overallPercent: null,
    isOverallIndeterminate: true,
    filesProcessed: 0,
    totalFiles: 0,
    startTime: null,
    endTime: null,
    elapsedSeconds: 0,
    etaSeconds: null,
    throughputSamples: [],
    completedSummary: undefined,
    activeFileIdHighlight: null,
    milestoneAnnouncement: null,
    alertError: null,
  };
}

export type BatchProgressAction =
  | { type: 'EVENT'; event: PipelineEvent }
  | { type: 'BATCH_EVENTS'; events: PipelineEvent[] }
  | { type: 'SET_ELAPSED'; elapsedSeconds: number }
  | { type: 'CANCEL_RUN' }
  | { type: 'HIGHLIGHT_FILE'; fileId: string | null }
  | { type: 'RESTORE_BATCH'; batchData: any }
  | { type: 'RESET_STEP'; step: PipelineStepKey; runId?: string };

export function batchProgressReducer(
  state: BatchProgressState,
  action: BatchProgressAction
): BatchProgressState {
  switch (action.type) {
    case 'CANCEL_RUN': {
      const nextSteps = { ...state.steps };
      for (const k of Object.keys(nextSteps) as PipelineStepKey[]) {
        const s = nextSteps[k];
        if (s.status === 'running' || s.status === 'waiting') {
          nextSteps[k] = { ...s, status: 'cancelled' };
        }
      }
      return {
        ...state,
        status: 'cancelled',
        steps: nextSteps,
        milestoneAnnouncement: 'Batch execution cancelled by user.',
      };
    }

    case 'HIGHLIGHT_FILE': {
      return {
        ...state,
        activeFileIdHighlight: action.fileId,
      };
    }

    case 'SET_ELAPSED': {
      return {
        ...state,
        elapsedSeconds: action.elapsedSeconds,
      };
    }

    case 'RESET_STEP': {
      const stepState = state.steps[action.step];
      if (!stepState) return state;
      const nextStep = {
        ...stepState,
        status: 'running' as const,
        done: 0,
        runId: action.runId || `run-${Date.now()}`,
        percent: 0,
        isIndeterminate: stepState.total === null,
        lastTs: Date.now(),
      };
      const nextSteps = { ...state.steps, [action.step]: nextStep };
      const { overallPercent, isOverallIndeterminate } = computeOverallProgress(nextSteps);
      return {
        ...state,
        steps: nextSteps,
        overallPercent,
        isOverallIndeterminate,
      };
    }

    case 'RESTORE_BATCH': {
      const b = action.batchData;
      if (!b) return state;

      const nextSteps = { ...state.steps };
      const nextFiles = { ...state.files };

      // Initialize / update files from batch.files
      const batchFiles = b.files || [];
      const totalFiles = batchFiles.length || state.totalFiles;
      let filesProcessed = 0;

      batchFiles.forEach((bf: any) => {
        const fileId = bf.id || bf.document_id || bf.name;
        const isDone = bf.status === 'done';
        if (isDone) filesProcessed++;

        const existingFile = nextFiles[fileId] || {
          file_id: fileId,
          file_name: bf.name || fileId,
          step: isDone ? 'ready' : (b.stage || 'ingest'),
          status: bf.status === 'done' ? 'done' : (bf.status === 'error' ? 'failed' : 'running'),
          done: isDone ? 100 : (bf.progress || 0),
          total: 100,
          unit: 'pages' as ProgressUnit,
          message: bf.error,
          steps: {
            ingest: createInitialFileStepProgress('ingest', 'files'),
            parse: createInitialFileStepProgress('parse', 'pages'),
            map: createInitialFileStepProgress('map', 'fields'),
            normalize: createInitialFileStepProgress('normalize', 'fields'),
            validate: createInitialFileStepProgress('validate', 'records'),
            ready: createInitialFileStepProgress('ready', 'records'),
          },
          lastTs: Date.now(),
        };

        if (isDone) {
          existingFile.status = 'done';
          existingFile.done = 100;
          for (const k of Object.keys(existingFile.steps) as PipelineStepKey[]) {
            existingFile.steps[k].status = 'done';
            existingFile.steps[k].percent = 100;
          }
        }
        nextFiles[fileId] = existingFile;
      });

      const isBatchDone = b.status === 'done' || b.stage === 'ready';

      // If batch is done, set all steps to 100%
      if (isBatchDone) {
        for (const k of Object.keys(nextSteps) as PipelineStepKey[]) {
          const prev = nextSteps[k];
          nextSteps[k] = {
            ...prev,
            status: 'done',
            percent: 100,
            done: prev.total || (k === 'ingest' ? totalFiles : 100),
            total: prev.total || (k === 'ingest' ? totalFiles : 100),
            isIndeterminate: false,
          };
        }
      }

      const { overallPercent, isOverallIndeterminate } = computeOverallProgress(nextSteps);

      // Compute elapsed from server timestamps if completed
      let elapsedSeconds = state.elapsedSeconds;
      if (b.created_at && b.updated_at) {
        const start = new Date(b.created_at).getTime();
        const end = new Date(b.updated_at).getTime();
        if (end >= start) {
          elapsedSeconds = Math.max(1, Math.round((end - start) / 1000));
        }
      }

      return {
        ...state,
        batchId: b.id || state.batchId,
        status: isBatchDone ? 'done' : (b.status || state.status),
        steps: nextSteps,
        files: nextFiles,
        totalFiles,
        filesProcessed: isBatchDone ? totalFiles : filesProcessed,
        overallPercent: isBatchDone ? 100 : overallPercent,
        isOverallIndeterminate: isBatchDone ? false : isOverallIndeterminate,
        elapsedSeconds,
        completedSummary: b.stats ? {
          fields: b.stats.total_fields,
          flagged: b.stats.needs_review,
          auto_approved: b.stats.auto_approved,
        } : state.completedSummary,
      };
    }

    case 'BATCH_EVENTS': {
      let cur = state;
      for (const ev of action.events) {
        cur = processSingleEvent(cur, ev);
      }
      return cur;
    }

    case 'EVENT': {
      return processSingleEvent(state, action.event);
    }

    default:
      return state;
  }
}

function processSingleEvent(state: BatchProgressState, event: PipelineEvent): BatchProgressState {
  if (!event) return state;

  // Handle Legacy AgentEvent fallback
  if (!('type' in event) || !event.type) {
    const leg = event as any;
    if (leg.step || leg.agent) {
      const logEv: LogEvent = {
        type: 'log',
        agent: leg.agent || 'Agent',
        level: leg.status === 'error' ? 'error' : leg.status === 'done' ? 'success' : 'info',
        message: leg.message || '',
        ts: leg.timestamp ? new Date(leg.timestamp).getTime() : Date.now(),
        file_id: leg.file_id,
      };
      return processSingleEvent(state, logEv);
    }
    return state;
  }

  const now = event.ts || Date.now();
  const startTime = state.startTime || now;

  switch (event.type) {
    case 'step_progress': {
      const ev = event as StepProgressEvent;
      const currentStep = state.steps[ev.step];
      if (!currentStep) return state;

      // Monotonicity check: Ignore stale events (older timestamp)
      // Exception: restart reset when run_id changed and status is running
      const isRestart = Boolean(ev.run_id && ev.run_id !== currentStep.runId && ev.status === 'running');
      if (!isRestart) {
        if (ev.ts && ev.ts < currentStep.lastTs) {
          return state; // Stale timestamp
        }
        if (ev.done < currentStep.done && ev.status === currentStep.status) {
          return state; // Stale backward done
        }
      }

      const effectiveDone = isRestart ? ev.done : Math.max(currentStep.done, ev.done);
      const effectiveTotal = ev.total !== undefined ? ev.total : currentStep.total;
      const { percent, isIndeterminate } = computeStepPercent(effectiveDone, effectiveTotal, ev.status);

      let milestoneAnnouncement = state.milestoneAnnouncement;
      if (ev.status === 'done' && currentStep.status !== 'done') {
        milestoneAnnouncement = `${currentStep.name} completed successfully.`;
      } else if (ev.status === 'failed' && currentStep.status !== 'failed') {
        milestoneAnnouncement = `${currentStep.name} failed: ${ev.message || 'Error occurred'}.`;
      }

      const updatedStep: StepProgressState = {
        ...currentStep,
        status: ev.status,
        done: effectiveDone,
        total: effectiveTotal,
        unit: ev.unit || currentStep.unit,
        percent,
        isIndeterminate,
        message: ev.message !== undefined ? ev.message : currentStep.message,
        flagged: ev.flagged !== undefined ? ev.flagged : currentStep.flagged,
        runId: ev.run_id || currentStep.runId,
        lastTs: now,
      };

      const nextSteps = {
        ...state.steps,
        [ev.step]: updatedStep,
      };

      const { overallPercent, isOverallIndeterminate } = computeOverallProgress(nextSteps);

      // Record throughput sample for ETA calculation if percent increased
      let nextSamples = state.throughputSamples;
      if (overallPercent !== null) {
        const lastSample = nextSamples[nextSamples.length - 1];
        if (!lastSample || (now - lastSample.ts >= 1500 && overallPercent > lastSample.percent)) {
          nextSamples = [...nextSamples.slice(-8), { ts: now, percent: overallPercent }];
        }
      }

      const etaSeconds = computeEta(nextSamples, overallPercent);

      // Check if all steps are done
      const allDone = PIPELINE_STEPS.every(s => nextSteps[s.key]?.status === 'done');
      const batchStatus = allDone ? 'done' : state.status === 'waiting' ? 'running' : state.status;

      return {
        ...state,
        startTime,
        status: batchStatus,
        steps: nextSteps,
        overallPercent,
        isOverallIndeterminate,
        throughputSamples: nextSamples,
        etaSeconds,
        milestoneAnnouncement,
      };
    }

    case 'file_progress': {
      const ev = event as FileProgressEvent;
      const fileId = ev.file_id || ev.file_name;
      const existingFile = state.files[fileId] || {
        file_id: fileId,
        file_name: ev.file_name || fileId,
        step: ev.step,
        status: ev.status,
        done: 0,
        total: ev.total,
        unit: ev.unit || 'pages',
        message: ev.message,
        steps: {
          ingest: createInitialFileStepProgress('ingest', 'files'),
          parse: createInitialFileStepProgress('parse', 'pages'),
          map: createInitialFileStepProgress('map', 'fields'),
          normalize: createInitialFileStepProgress('normalize', 'fields'),
          validate: createInitialFileStepProgress('validate', 'records'),
          ready: createInitialFileStepProgress('ready', 'records'),
        },
        lastTs: 0,
      };

      // Monotonic check for file
      if (ev.ts && ev.ts < existingFile.lastTs && ev.status === existingFile.status) {
        return state;
      }

      const fileStep = existingFile.steps[ev.step] || createInitialFileStepProgress(ev.step, ev.unit);
      const fileStepPct = (ev.total !== null && ev.total > 0)
        ? Math.min(100, Math.max(0, Math.round((ev.done / ev.total) * 100)))
        : (ev.status === 'done' ? 100 : null);

      const updatedFileStep: FileStepProgress = {
        ...fileStep,
        status: ev.status,
        done: Math.max(fileStep.done, ev.done),
        total: ev.total !== undefined ? ev.total : fileStep.total,
        unit: ev.unit || fileStep.unit,
        percent: fileStepPct,
      };

      const updatedSteps = {
        ...existingFile.steps,
        [ev.step]: updatedFileStep,
      };

      const updatedFile: FileProgressState = {
        ...existingFile,
        file_name: ev.file_name || existingFile.file_name,
        step: ev.step,
        status: ev.status,
        done: Math.max(existingFile.done, ev.done),
        total: ev.total !== undefined ? ev.total : existingFile.total,
        unit: ev.unit || existingFile.unit,
        message: ev.message !== undefined ? ev.message : existingFile.message,
        steps: updatedSteps,
        lastTs: now,
      };

      const nextFiles = {
        ...state.files,
        [fileId]: updatedFile,
      };

      const totalFiles = Math.max(state.totalFiles, Object.keys(nextFiles).length);
      const filesProcessed = Object.values(nextFiles).filter(f => f.status === 'done').length;

      return {
        ...state,
        startTime,
        files: nextFiles,
        totalFiles,
        filesProcessed,
      };
    }

    case 'log': {
      const ev = event as LogEvent;
      return {
        ...state,
        logs: [...state.logs.slice(-300), ev],
      };
    }

    case 'batch_done': {
      const ev = event as BatchDoneEvent;
      const nextSteps = { ...state.steps };
      for (const def of PIPELINE_STEPS) {
        const s = nextSteps[def.key];
        nextSteps[def.key] = {
          ...s,
          status: 'done',
          percent: 100,
          done: s.total || s.done || 1,
          total: s.total || s.done || 1,
          isIndeterminate: false,
        };
      }

      return {
        ...state,
        status: 'done',
        endTime: now,
        steps: nextSteps,
        overallPercent: 100,
        isOverallIndeterminate: false,
        etaSeconds: null,
        completedSummary: ev.summary,
        filesProcessed: state.totalFiles || Object.keys(state.files).length,
        milestoneAnnouncement: `Standardization Complete. ${ev.summary.fields} fields identified, ${ev.summary.flagged} need review.`,
      };
    }

    case 'error': {
      const ev = event as BatchErrorEvent;
      if (ev.step && state.steps[ev.step]) {
        const s = state.steps[ev.step];
        const nextSteps = {
          ...state.steps,
          [ev.step]: {
            ...s,
            status: 'failed' as const,
            message: ev.message,
          },
        };
        return {
          ...state,
          steps: nextSteps,
          alertError: `${s.name} error: ${ev.message}`,
        };
      }

      return {
        ...state,
        status: 'failed',
        alertError: ev.message,
        milestoneAnnouncement: `Execution encountered an error: ${ev.message}`,
      };
    }

    default:
      return state;
  }
}
