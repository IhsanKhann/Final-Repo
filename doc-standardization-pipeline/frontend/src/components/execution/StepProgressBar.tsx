import React from 'react';
import type { StepStatus } from '../../api/types';

export interface StepProgressBarProps {
  percent: number | null; // null = indeterminate
  status: StepStatus | 'default';
  isIndeterminate?: boolean;
  ariaLabelledBy?: string;
  ariaValueText?: string;
  height?: number;
  className?: string;
  id?: string;
}

export function StepProgressBar({
  percent,
  status,
  isIndeterminate = false,
  ariaLabelledBy,
  ariaValueText,
  height = 10,
  className = '',
  id,
}: StepProgressBarProps) {
  const isRunning = status === 'running';
  const effectiveIndeterminate = isIndeterminate || (percent === null && isRunning);
  const clampedPercent = percent !== null ? Math.min(100, Math.max(0, percent)) : 0;

  // Determine fill color based on status
  let fillColor = 'var(--color-accent)';
  if (status === 'done') fillColor = 'var(--color-success)';
  else if (status === 'warning') fillColor = 'var(--color-warning)';
  else if (status === 'failed') fillColor = 'var(--color-error)';
  else if (status === 'cancelled' || status === 'waiting') fillColor = 'var(--color-neutral)';

  return (
    <div
      id={id}
      role="progressbar"
      aria-labelledby={ariaLabelledBy}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={effectiveIndeterminate ? undefined : clampedPercent}
      aria-valuetext={ariaValueText || (effectiveIndeterminate ? 'Working...' : `${clampedPercent} percent`)}
      aria-busy={effectiveIndeterminate ? 'true' : undefined}
      className={`progress-bar-track ${className}`}
      style={{
        position: 'relative',
        width: '100%',
        height,
        borderRadius: height / 2,
        background: 'var(--color-surface-2)',
        border: '1px solid var(--color-border)',
        overflow: 'hidden',
        boxSizing: 'border-box',
      }}
    >
      {effectiveIndeterminate ? (
        // Indeterminate Animated Striped Fill
        <div
          className="indeterminate-animated-bar"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            height: '100%',
            width: '100%',
            backgroundColor: fillColor,
            backgroundImage:
              'linear-gradient(45deg, rgba(255,255,255,0.2) 25%, transparent 25%, transparent 50%, rgba(255,255,255,0.2) 50%, rgba(255,255,255,0.2) 75%, transparent 75%, transparent)',
            backgroundSize: '24px 24px',
            animation: 'stripe-move 1s linear infinite',
            borderRadius: height / 2,
          }}
        />
      ) : (
        // Deterministic Fill with 200ms smooth width transition
        <div
          className={`progress-fill ${isRunning ? 'striped-running' : ''}`}
          style={{
            width: `${clampedPercent}%`,
            height: '100%',
            backgroundColor: fillColor,
            borderRadius: height / 2,
            transition: 'width 200ms ease',
            backgroundImage: isRunning
              ? 'linear-gradient(45deg, rgba(255,255,255,0.2) 25%, transparent 25%, transparent 50%, rgba(255,255,255,0.2) 50%, rgba(255,255,255,0.2) 75%, transparent 75%, transparent)'
              : undefined,
            backgroundSize: isRunning ? '20px 20px' : undefined,
            animation: isRunning ? 'stripe-move 1.2s linear infinite' : undefined,
          }}
        />
      )}
    </div>
  );
}
