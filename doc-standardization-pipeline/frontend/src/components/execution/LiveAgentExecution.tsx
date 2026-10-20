import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Cpu, Info, CheckCircle2, ArrowRight } from 'lucide-react';
import type { UseBatchProgressReturn } from '../../hooks/useBatchProgress';
import { PIPELINE_STEPS } from '../../hooks/progressReducer';
import { OverallProgressBar } from './OverallProgressBar';
import { StepRow } from './StepRow';
import { FilesProgressSection } from './FilesProgressSection';
import { AgentTimeline } from './AgentTimeline';

export interface LiveAgentExecutionProps {
  progress: UseBatchProgressReturn;
  onNavigateReview?: () => void;
  onNavigateDataset?: () => void;
}

export function LiveAgentExecution({
  progress,
  onNavigateReview,
  onNavigateDataset,
}: LiveAgentExecutionProps) {
  const navigate = useNavigate();
  const {
    state,
    isReconnecting,
    cancelRun,
    retryStep,
    retryFile,
    highlightFile,
  } = progress;

  const {
    status,
    steps,
    files,
    logs,
    overallPercent,
    isOverallIndeterminate,
    filesProcessed,
    totalFiles,
    elapsedSeconds,
    etaSeconds,
    completedSummary,
    activeFileIdHighlight,
    milestoneAnnouncement,
    alertError,
  } = state;

  const isDone = status === 'done';

  const handleOpenReview = () => {
    if (onNavigateReview) onNavigateReview();
    else navigate('/review');
  };

  const handleViewDataset = () => {
    if (onNavigateDataset) onNavigateDataset();
    else navigate('/dataset');
  };

  return (
    <div
      className="card live-agent-execution-card"
      style={{
        borderColor: isDone ? 'var(--color-success-border)' : 'var(--color-accent-muted)',
        background: 'var(--color-surface)',
        borderRadius: 12,
        overflow: 'hidden',
        boxShadow: 'var(--shadow-md)',
      }}
    >
      {/* ─── Screen Reader Announcements ─── */}
      <div
        className="sr-only"
        aria-live="polite"
        aria-atomic="true"
        style={{
          position: 'absolute',
          width: 1,
          height: 1,
          padding: 0,
          margin: -1,
          overflow: 'hidden',
          clip: 'rect(0, 0, 0, 0)',
          whiteSpace: 'nowrap',
          border: 0,
        }}
      >
        {milestoneAnnouncement}
      </div>

      {alertError && (
        <div
          role="alert"
          className="sr-only"
          style={{
            position: 'absolute',
            width: 1,
            height: 1,
            padding: 0,
            margin: -1,
            overflow: 'hidden',
            clip: 'rect(0, 0, 0, 0)',
            whiteSpace: 'nowrap',
            border: 0,
          }}
        >
          {alertError}
        </div>
      )}

      {/* ─── Card Header ─── */}
      <div
        className="card-header"
        style={{
          padding: '14px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid var(--color-border-subtle)',
          background: 'var(--color-surface-2)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              background: isDone ? 'var(--color-success-bg)' : 'var(--color-accent-light)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: isDone ? 'var(--color-success)' : 'var(--color-accent)',
            }}
            aria-hidden="true"
          >
            <Cpu size={18} />
          </div>
          <div>
            <h2
              className="card-title"
              style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: 'var(--color-text-primary)' }}
            >
              Live Agent Execution
            </h2>
            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
              Real-time multi-agent standardization pipeline with canonical schema mapping
            </div>
          </div>
        </div>
      </div>

      <div className="card-body" style={{ padding: '20px' }}>
        {/* ─── Informational Banner (Restored on leave & return) ─── */}
        <div
          style={{
            fontSize: '0.8125rem',
            color: 'var(--color-text-secondary)',
            background: 'var(--color-info-bg)',
            border: '1px solid var(--color-info-border)',
            padding: '10px 14px',
            borderRadius: 8,
            marginBottom: 20,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <Info size={16} color="var(--color-info)" style={{ flexShrink: 0 }} aria-hidden="true" />
          <span>You can leave this page; we will notify you when review is ready.</span>
        </div>

        {/* ─── 1. Overall Progress Bar ─── */}
        <OverallProgressBar
          overallPercent={overallPercent}
          isOverallIndeterminate={isOverallIndeterminate}
          status={status}
          filesProcessed={filesProcessed}
          totalFiles={totalFiles}
          elapsedSeconds={elapsedSeconds}
          etaSeconds={etaSeconds}
          isReconnecting={isReconnecting}
          onCancel={cancelRun}
        />

        {/* ─── 2. 6-Step Per-Step Progress Rows ─── */}
        <div
          className="steps-container"
          role="region"
          aria-label="Pipeline Steps Progress"
          style={{ marginBottom: 20 }}
        >
          {PIPELINE_STEPS.map((s) => {
            const stepState = steps[s.key];
            return (
              <StepRow
                key={s.key}
                stepState={stepState}
                onRetry={retryStep}
              />
            );
          })}
        </div>

        {/* ─── 3. Files Section (Expandable per file) ─── */}
        <FilesProgressSection
          files={files}
          activeFileIdHighlight={activeFileIdHighlight}
          onRetryFile={retryFile}
        />

        {/* ─── 4. Agent Activity Timeline (SSE Stream) ─── */}
        <div style={{ marginBottom: 20 }}>
          <AgentTimeline
            logs={logs}
            onHighlightFile={highlightFile}
            activeFileIdHighlight={activeFileIdHighlight}
          />
        </div>

        {/* ─── 5. Standardization Complete Card ─── */}
        {isDone && (
          <div
            tabIndex={-1}
            style={{
              padding: '16px 20px',
              background: 'var(--color-success-bg)',
              borderRadius: 10,
              border: '1.5px solid var(--color-success-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: 14,
              boxShadow: 'var(--shadow-sm)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: '50%',
                  background: 'var(--color-success)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#ffffff',
                }}
                aria-hidden="true"
              >
                <CheckCircle2 size={22} />
              </div>

              <div>
                <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--color-text-primary)' }}>
                  Standardization Complete
                </div>
                <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', marginTop: 2 }}>
                  {completedSummary && completedSummary.flagged > 0
                    ? `${completedSummary.fields} fields identified, ${completedSummary.flagged} need review.`
                    : 'Source fields extracted and ready for validation.'}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleOpenReview}
                style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <span>Open Review Screen</span>
                <ArrowRight size={15} />
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleViewDataset}
                style={{ minHeight: 44 }}
              >
                <span>View Dataset</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
