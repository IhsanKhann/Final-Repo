import React from 'react';
import {
  Clock,
  RefreshCw,
  Check,
  AlertTriangle,
  XCircle,
  Ban,
  RotateCw,
} from 'lucide-react';
import type { StepProgressState } from '../../hooks/progressReducer';
import { StepProgressBar } from './StepProgressBar';

export interface StepRowProps {
  stepState: StepProgressState;
  onRetry?: (step: StepProgressState['step']) => void;
}

export function StepRow({ stepState, onRetry }: StepRowProps) {
  const {
    step,
    stepNumber,
    name,
    sublabel,
    status,
    done,
    total,
    unit,
    percent,
    isIndeterminate,
    message,
    flagged,
  } = stepState;

  const labelId = `step-label-${step}`;

  // Counts string
  let countsText = '-';
  if (status === 'running' && isIndeterminate) {
    countsText = 'Working...';
  } else if (status !== 'waiting') {
    if (total !== null && total > 0) {
      countsText = `${done} of ${total} ${unit}`;
    } else if (done > 0) {
      countsText = `${done} ${unit}`;
    }
  }

  // Accessible value text
  const ariaValueText = `${name}: ${countsText}${percent !== null ? `, ${percent} percent` : ''}`;

  // Status Chip Details (Icon + Text + Colors)
  let statusIcon = <Clock size={13} aria-hidden="true" />;
  let statusText = 'Waiting';
  let chipBg = 'var(--color-surface-2)';
  let chipBorder = 'var(--color-border)';
  let chipColor = 'var(--color-text-muted)';

  switch (status) {
    case 'running':
      statusIcon = <RefreshCw size={13} className="animate-spin" aria-hidden="true" />;
      statusText = 'Running';
      chipBg = 'var(--color-accent-light)';
      chipBorder = 'var(--color-accent-muted)';
      chipColor = 'var(--color-accent)';
      break;
    case 'done':
      statusIcon = <Check size={13} aria-hidden="true" />;
      statusText = 'Done';
      chipBg = 'var(--color-success-bg)';
      chipBorder = 'var(--color-success-border)';
      chipColor = 'var(--color-success)';
      break;
    case 'warning':
      statusIcon = <AlertTriangle size={13} aria-hidden="true" />;
      statusText = flagged && flagged > 0
        ? `Done with warnings (${flagged} fields need review)`
        : 'Done with warnings';
      chipBg = 'var(--color-warning-bg)';
      chipBorder = 'var(--color-warning-border)';
      chipColor = 'var(--color-warning)';
      break;
    case 'failed':
      statusIcon = <XCircle size={13} aria-hidden="true" />;
      statusText = 'Failed';
      chipBg = 'var(--color-error-bg)';
      chipBorder = 'var(--color-error-border)';
      chipColor = 'var(--color-error)';
      break;
    case 'cancelled':
      statusIcon = <Ban size={13} aria-hidden="true" />;
      statusText = 'Cancelled';
      chipBg = 'var(--color-surface-2)';
      chipBorder = 'var(--color-border)';
      chipColor = 'var(--color-text-muted)';
      break;
    case 'waiting':
    default:
      break;
  }

  return (
    <div
      className="step-execution-row"
      style={{
        padding: '12px 14px',
        borderRadius: 8,
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border-subtle)',
        marginBottom: 8,
        transition: 'all 0.15s ease',
      }}
    >
      {/* ─── Desktop Layout (>= 1024px) ─── */}
      <div className="step-desktop-view">
        {/* Step Identity (Number + Name + Sublabel) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 200, flexShrink: 0 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '0.75rem',
              fontWeight: 700,
              background: status === 'done' ? 'var(--color-success)' : status === 'running' ? 'var(--color-accent)' : 'var(--color-surface-2)',
              color: status === 'done' || status === 'running' ? '#ffffff' : 'var(--color-text-secondary)',
              border: `1.5px solid ${status === 'done' ? 'var(--color-success)' : status === 'running' ? 'var(--color-accent)' : 'var(--color-border)'}`,
              flexShrink: 0,
            }}
            aria-hidden="true"
          >
            {status === 'done' ? <Check size={14} /> : stepNumber}
          </div>

          <div>
            <div id={labelId} style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>
              {stepNumber} {name}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
              {sublabel}
            </div>
          </div>
        </div>

        {/* Progress Bar (Filling Middle) */}
        <div style={{ flex: 1, padding: '0 16px' }}>
          <StepProgressBar
            percent={percent}
            status={status}
            isIndeterminate={isIndeterminate}
            ariaLabelledBy={labelId}
            ariaValueText={ariaValueText}
            height={10}
          />
        </div>

        {/* Right Info: Percent + Status Chip + Counts */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'flex-end', minWidth: 280, flexShrink: 0 }}>
          {/* Percent text */}
          <span
            style={{
              fontSize: '0.85rem',
              fontWeight: 700,
              fontVariantNumeric: 'tabular-nums',
              minWidth: 44,
              textAlign: 'right',
              color: status === 'done' ? 'var(--color-success)' : status === 'running' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
            }}
          >
            {isIndeterminate ? 'Working…' : percent !== null ? `${percent}%` : '0%'}
          </span>

          {/* Status Chip */}
          <span
            className="status-chip"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '3px 9px',
              borderRadius: 9999,
              fontSize: '0.75rem',
              fontWeight: 600,
              background: chipBg,
              color: chipColor,
              border: `1px solid ${chipBorder}`,
              whiteSpace: 'nowrap',
            }}
          >
            {statusIcon}
            <span>{statusText}</span>
          </span>

          {/* Counts */}
          <span
            style={{
              fontSize: '0.8rem',
              color: 'var(--color-text-secondary)',
              minWidth: 95,
              textAlign: 'right',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {countsText}
          </span>

          {/* Retry Button if failed */}
          {status === 'failed' && onRetry && (
            <button
              className="btn btn-sm btn-outline-danger"
              style={{ minHeight: 44, minWidth: 44, display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px' }}
              onClick={() => onRetry(step)}
              aria-label={`Retry ${name} step`}
            >
              <RotateCw size={13} />
              <span>Retry</span>
            </button>
          )}
        </div>
      </div>

      {/* ─── Compact Card Layout (Under 1024px) ─── */}
      <div className="step-mobile-view">
        {/* Line 1: Name + Status Chip */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontWeight: 700, fontSize: '0.8rem', color: 'var(--color-accent)' }}>
              #{stepNumber}
            </span>
            <span style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>
              {name}
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
              ({sublabel})
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '2px 8px',
                borderRadius: 9999,
                fontSize: '0.75rem',
                fontWeight: 600,
                background: chipBg,
                color: chipColor,
                border: `1px solid ${chipBorder}`,
              }}
            >
              {statusIcon}
              <span>{statusText}</span>
            </span>

            {status === 'failed' && onRetry && (
              <button
                className="btn btn-sm btn-outline-danger"
                style={{ minHeight: 44, minWidth: 44, padding: '4px 8px' }}
                onClick={() => onRetry(step)}
                aria-label={`Retry ${name} step`}
              >
                <RotateCw size={12} />
              </button>
            )}
          </div>
        </div>

        {/* Line 2: Full Width Progress Bar */}
        <div style={{ marginBottom: 6 }}>
          <StepProgressBar
            percent={percent}
            status={status}
            isIndeterminate={isIndeterminate}
            ariaLabelledBy={labelId}
            ariaValueText={ariaValueText}
            height={8}
          />
        </div>

        {/* Line 3: Counts and Percent */}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>
          <span>{countsText}</span>
          <span style={{ fontWeight: 700, color: status === 'done' ? 'var(--color-success)' : 'var(--color-text-primary)' }}>
            {isIndeterminate ? 'Working…' : percent !== null ? `${percent}%` : '0%'}
          </span>
        </div>
      </div>

      {/* Error / Failure message banner if failed */}
      {status === 'failed' && message && (
        <div
          role="alert"
          style={{
            marginTop: 8,
            padding: '6px 10px',
            borderRadius: 6,
            background: 'var(--color-error-bg)',
            border: '1px solid var(--color-error-border)',
            color: 'var(--color-error)',
            fontSize: '0.75rem',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <AlertTriangle size={14} />
          <span>{message}</span>
        </div>
      )}
    </div>
  );
}
