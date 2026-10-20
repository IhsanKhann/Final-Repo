import { useEffect, useReducer, useRef, useState, useCallback } from 'react';
import {
  batchProgressReducer,
  createInitialBatchProgressState,
  type BatchProgressState,
} from './progressReducer';
import type { PipelineEvent, PipelineStepKey } from '../api/types';
import { getBatch, cancelBatch, retryBatchFile, retryBatchStep } from '../api/client';
import { ENDPOINTS } from '../api/endpoints';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

export interface UseBatchProgressReturn {
  state: BatchProgressState;
  isReconnecting: boolean;
  isPolling: boolean;
  cancelRun: () => Promise<void>;
  retryStep: (step: PipelineStepKey) => Promise<void>;
  retryFile: (fileId: string) => Promise<void>;
  highlightFile: (fileId: string | null) => void;
  refetchState: () => Promise<void>;
  pushEvent: (event: PipelineEvent) => void;
}

export function useBatchProgress(batchId?: string): UseBatchProgressReturn {
  const [state, dispatch] = useReducer(
    batchProgressReducer,
    batchId || '',
    createInitialBatchProgressState
  );

  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);

  // Throttling buffer: events collected and flushed at max 10fps (every 100ms)
  const eventQueueRef = useRef<PipelineEvent[]>([]);
  const rafIdRef = useRef<number | null>(null);
  const lastFlushTimeRef = useRef<number>(0);

  // SSE / reconnect refs
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastEventIdRef = useRef<string | null>(null);
  const isCancelledRef = useRef(false);

  // Flush queued events to reducer at throttled rate (<= 10 updates / sec)
  const flushEventQueue = useCallback(() => {
    rafIdRef.current = null;
    if (eventQueueRef.current.length === 0) return;

    const eventsToProcess = [...eventQueueRef.current];
    eventQueueRef.current = [];
    lastFlushTimeRef.current = Date.now();

    dispatch({ type: 'BATCH_EVENTS', events: eventsToProcess });
  }, []);

  const queueEvent = useCallback((event: PipelineEvent) => {
    eventQueueRef.current.push(event);

    const now = Date.now();
    const timeSinceLastFlush = now - lastFlushTimeRef.current;
    const minIntervalMs = 100; // 10 updates per second

    if (timeSinceLastFlush >= minIntervalMs) {
      if (rafIdRef.current === null) {
        rafIdRef.current = requestAnimationFrame(flushEventQueue);
      }
    } else {
      if (rafIdRef.current === null) {
        const waitMs = minIntervalMs - timeSinceLastFlush;
        setTimeout(() => {
          if (rafIdRef.current === null) {
            rafIdRef.current = requestAnimationFrame(flushEventQueue);
          }
        }, waitMs);
      }
    }
  }, [flushEventQueue]);

  // Fetch current batch state from server to restore state on initial mount or reconnect
  const restoreFromApi = useCallback(async () => {
    if (!batchId) return;
    try {
      const data = await getBatch(batchId);
      if (data) {
        dispatch({ type: 'RESTORE_BATCH', batchData: data });
      }
    } catch (err) {
      console.warn('[useBatchProgress] Could not restore batch state from API:', err);
    }
  }, [batchId]);

  // Fallback Polling (used when SSE fails or is unavailable)
  const startPollingFallback = useCallback(() => {
    if (pollingIntervalRef.current || !batchId || isCancelledRef.current) return;
    setIsPolling(true);
    setIsReconnecting(false);

    pollingIntervalRef.current = setInterval(async () => {
      try {
        const b = await getBatch(batchId);
        if (b) {
          dispatch({ type: 'RESTORE_BATCH', batchData: b });
          if (b.status === 'done' || b.status === 'failed' || b.status === 'cancelled') {
            if (pollingIntervalRef.current) {
              clearInterval(pollingIntervalRef.current);
              pollingIntervalRef.current = null;
            }
          }
        }
      } catch (err) {
        console.warn('[useBatchProgress] Polling tick failed:', err);
      }
    }, 2000);
  }, [batchId]);

  // SSE Connect with exponential backoff reconnect (1s, 2s, 4s, max 15s)
  const connectSSE = useCallback(() => {
    if (!batchId || USE_MOCK || isCancelledRef.current) return;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    try {
      const url = new URL(ENDPOINTS.batches.events(batchId), window.location.origin);
      if (lastEventIdRef.current) {
        url.searchParams.set('lastEventId', lastEventIdRef.current);
      }

      const es = new EventSource(url.toString());
      eventSourceRef.current = es;

      es.onopen = () => {
        setIsReconnecting(false);
        setIsPolling(false);
        reconnectAttemptRef.current = 0;
      };

      es.onmessage = (e) => {
        try {
          if (e.lastEventId) {
            lastEventIdRef.current = e.lastEventId;
          }
          const parsed = JSON.parse(e.data);
          queueEvent(parsed);
        } catch {
          // ignore parse errors
        }
      };

      es.onerror = () => {
        es.close();
        eventSourceRef.current = null;

        if (isCancelledRef.current) return;

        // Exponential backoff: 1s, 2s, 4s, 8s, up to max 15s
        reconnectAttemptRef.current++;
        const attempt = reconnectAttemptRef.current;

        if (attempt > 5) {
          // Fall back to polling if SSE repeatedly fails
          startPollingFallback();
          return;
        }

        setIsReconnecting(true);
        const delayMs = Math.min(1000 * Math.pow(2, attempt - 1), 15000);

        reconnectTimeoutRef.current = setTimeout(async () => {
          if (isCancelledRef.current) return;
          await restoreFromApi();
          connectSSE();
        }, delayMs);
      };
    } catch {
      startPollingFallback();
    }
  }, [batchId, queueEvent, restoreFromApi, startPollingFallback]);

  // Initial load: restore state from API, then start SSE
  useEffect(() => {
    if (!batchId) return;

    isCancelledRef.current = false;
    restoreFromApi().then(() => {
      if (!USE_MOCK) {
        connectSSE();
      }
    });

    return () => {
      isCancelledRef.current = true;
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
      }
    };
  }, [batchId, connectSSE, restoreFromApi]);

  // Live elapsed timer while batch is running
  useEffect(() => {
    if (!state.startTime || state.status === 'done' || state.status === 'failed' || state.status === 'cancelled') {
      return;
    }

    const timer = setInterval(() => {
      const now = Date.now();
      const elapsed = Math.max(0, Math.floor((now - state.startTime!) / 1000));
      dispatch({ type: 'SET_ELAPSED', elapsedSeconds: elapsed });
    }, 1000);

    return () => clearInterval(timer);
  }, [state.startTime, state.status]);

  // Public Actions
  const cancelRun = useCallback(async () => {
    if (!batchId) return;
    try {
      isCancelledRef.current = true;
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      dispatch({ type: 'CANCEL_RUN' });
      await cancelBatch(batchId);
    } catch (err) {
      console.warn('[useBatchProgress] Cancel call note:', err);
    }
  }, [batchId]);

  const retryStep = useCallback(async (step: PipelineStepKey) => {
    if (!batchId) return;
    dispatch({ type: 'RESET_STEP', step });
    try {
      await retryBatchStep(batchId, step);
    } catch (err) {
      console.warn('[useBatchProgress] Retry step note:', err);
    }
  }, [batchId]);

  const retryFile = useCallback(async (fileId: string) => {
    if (!batchId) return;
    try {
      await retryBatchFile(batchId, fileId);
    } catch (err) {
      console.warn('[useBatchProgress] Retry file note:', err);
    }
  }, [batchId]);

  const highlightFile = useCallback((fileId: string | null) => {
    dispatch({ type: 'HIGHLIGHT_FILE', fileId });
  }, []);

  return {
    state,
    isReconnecting,
    isPolling,
    cancelRun,
    retryStep,
    retryFile,
    highlightFile,
    refetchState: restoreFromApi,
    pushEvent: queueEvent,
  };
}
