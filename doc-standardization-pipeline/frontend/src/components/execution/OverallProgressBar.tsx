import React, { useState } from 'react';
import { Ban, WifiOff, Clock } from 'lucide-react';
import { StepProgressBar } from './StepProgressBar';
import { CancelConfirmModal } from './CancelConfirmModal';

export interface OverallProgressBarProps {
  overallPercent: number | null;
  isOverallIndeterminate: boolean;
  status: 'waiting' | 'running' | 'done' | 'warning' | 'failed' | 'cancelled';
  filesProcessed: number;
  totalFiles: number;
  elapsedSeconds: number;
  etaSeconds: number | null;
  isReconnecting: boolean;
  onCancel: () => Promise<void>;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export function OverallProgressBar({
  overallPercent,
  isOverallIndeterminate,
  status,
  filesProcessed,
  totalFiles,
  elapsedSeconds,
  etaSeconds,
  isReconnecting,
  onCancel,
}: OverallProgressBarProps) {
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  const isRunning = status === 'running' || status === 'waiting';
  const isDone = status === 'done';

  const elapsedText = `${formatDuration(elapsedSeconds)} elapsed`;
  const etaText = etaSeconds !== null ? `~${formatDuration(etaSeconds)} remaining` : null;

  const handleConfirmCancel = async () => {
    setIsCancelling(true);
    try {
      await onCancel();
    } finally {
      setIsCancelling(false);
      setShowCancelModal(false);
    }
  };

  return (
    <div
      className="card overall-progress-card"
      style={{
        padding: '16px 20px',
        marginBottom: 16,
        background: 'var(--color-surface)',
        border: `1.5px solid ${isDone ? 'var(--color-success-border)' : 'var(--color-border)'}`,
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      {/* Top Header Row: Title + Status + Timer + Cancel Button */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
          marginBottom: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            id="overall-progress-title"
            style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--color-text-primary)' }}
          >
            Overall Batch Progress
          </span>

          {isReconnecting && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                padding: '2px 8px',
                borderRadius: 9999,
                fontSize: '0.75rem',
                fontWeight: 600,
                background: 'var(--color-warning-bg)',
                color: 'var(--color-warning)',
                border: '1px solid var(--color-warning-border)',
              }}
            >
              <WifiOff size={12} className="animate-pulse" />
              <span>Reconnecting…</span>
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {/* Elapsed & ETA Timer */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: '0.8125rem',
              color: 'var(--color-text-secondary)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            <Clock size={14} color="var(--color-text-muted)" aria-hidden="true" />
            <span>{elapsedText}</span>
            {etaText && (
              <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>
                ({etaText})
              </span>
            )}
          </div>

          {/* Cancel Button */}
          {isRunning && (
            <button
              type="button"
              className="btn btn-sm btn-outline-danger"
              style={{ minHeight: 44, padding: '4px 12px', display: 'flex', alignItems: 'center', gap: 6 }}
              onClick={() => setShowCancelModal(true)}
              aria-label="Cancel pipeline run"
            >
              <Ban size={14} />
              <span>Cancel run</span>
            </button>
          )}
        </div>
      </div>

      {/* Middle Progress Bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 8 }}>
        <div style={{ flex: 1 }}>
          <StepProgressBar
            percent={isDone ? 100 : overallPercent}
            status={status}
            isIndeterminate={isOverallIndeterminate}
            ariaLabelledBy="overall-progress-title"
            ariaValueText={`Overall batch progress: ${overallPercent !== null ? `${overallPercent} percent` : 'Working'}`}
            height={12}
          />
        </div>

        <div
          style={{
            fontSize: '1.1rem',
            fontWeight: 800,
            fontVariantNumeric: 'tabular-nums',
            color: isDone ? 'var(--color-success)' : 'var(--color-text-primary)',
            minWidth: 50,
            textAlign: 'right',
          }}
        >
          {isOverallIndeterminate ? 'Working…' : overallPercent !== null ? `${overallPercent}%` : '0%'}
        </div>
      </div>

      {/* Bottom Sub-info: Processed Files summary */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: '0.8rem',
          color: 'var(--color-text-secondary)',
        }}
      >
        <span>
          <strong>{filesProcessed}</strong> of <strong>{totalFiles || 1}</strong> file{totalFiles !== 1 ? 's' : ''} fully processed
        </span>

        {status === 'cancelled' && (
          <span style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
            Run was cancelled
          </span>
        )}
      </div>

      {/* Cancel Confirmation Dialog */}
      <CancelConfirmModal
        isOpen={showCancelModal}
        onConfirm={handleConfirmCancel}
        onClose={() => setShowCancelModal(false)}
        isLoading={isCancelling}
      />
    </div>
  );
}
