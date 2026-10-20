import React, { useState } from 'react';
import {
  FileSpreadsheet,
  FileText,
  FileCode,
  File,
  ChevronDown,
  ChevronRight,
  Check,
  RefreshCw,
  AlertCircle,
  XCircle,
  RotateCw,
  Clock,
} from 'lucide-react';
import type { FileProgressState } from '../../hooks/progressReducer';
import { PIPELINE_STEPS } from '../../hooks/progressReducer';
import { StepProgressBar } from './StepProgressBar';

export interface FilesProgressSectionProps {
  files: Record<string, FileProgressState>;
  activeFileIdHighlight: string | null;
  onRetryFile?: (fileId: string) => void;
}

function getFileIcon(fileName: string) {
  const lower = fileName.toLowerCase();
  if (lower.endsWith('.xlsx') || lower.endsWith('.xls') || lower.endsWith('.csv')) {
    return <FileSpreadsheet size={16} color="var(--color-success)" />;
  }
  if (lower.endsWith('.pdf')) {
    return <FileText size={16} color="var(--color-error)" />;
  }
  if (lower.endsWith('.html') || lower.endsWith('.htm') || lower.endsWith('.xml') || lower.endsWith('.json')) {
    return <FileCode size={16} color="var(--color-accent)" />;
  }
  return <File size={16} color="var(--color-text-secondary)" />;
}

export function FilesProgressSection({
  files,
  activeFileIdHighlight,
  onRetryFile,
}: FilesProgressSectionProps) {
  const [expandedFiles, setExpandedFiles] = useState<Record<string, boolean>>({});

  const fileList = Object.values(files);
  if (fileList.length === 0) return null;

  const toggleExpand = (fileId: string) => {
    setExpandedFiles((prev) => ({
      ...prev,
      [fileId]: !prev[fileId],
    }));
  };

  return (
    <div
      className="card files-progress-card"
      style={{
        padding: '16px 20px',
        marginBottom: 16,
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: '0.95rem',
            fontWeight: 700,
            color: 'var(--color-text-primary)',
          }}
        >
          Files (expandable per file)
        </h3>
        <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
          {fileList.length} document{fileList.length !== 1 ? 's' : ''} in batch
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {fileList.map((file) => {
          const isExpanded = !!expandedFiles[file.file_id];
          const isHighlighted = activeFileIdHighlight === file.file_id || activeFileIdHighlight === file.file_name;

          // Status Chip styling
          let chipBg = 'var(--color-surface-2)';
          let chipBorder = 'var(--color-border)';
          let chipColor = 'var(--color-text-muted)';
          let chipIcon = <Clock size={12} />;
          let chipText = 'Queued';

          switch (file.status) {
            case 'running':
              chipBg = 'var(--color-accent-light)';
              chipBorder = 'var(--color-accent-muted)';
              chipColor = 'var(--color-accent)';
              chipIcon = <RefreshCw size={12} className="animate-spin" />;
              chipText = 'Processing';
              break;
            case 'done':
              chipBg = 'var(--color-success-bg)';
              chipBorder = 'var(--color-success-border)';
              chipColor = 'var(--color-success)';
              chipIcon = <Check size={12} />;
              chipText = 'Done';
              break;
            case 'warning':
              chipBg = 'var(--color-warning-bg)';
              chipBorder = 'var(--color-warning-border)';
              chipColor = 'var(--color-warning)';
              chipIcon = <AlertCircle size={12} />;
              chipText = 'Review Needed';
              break;
            case 'failed':
              chipBg = 'var(--color-error-bg)';
              chipBorder = 'var(--color-error-border)';
              chipColor = 'var(--color-error)';
              chipIcon = <XCircle size={12} />;
              chipText = 'Failed';
              break;
            default:
              break;
          }

          // Progress text summary
          let progressSummaryText = '';
          if (file.status === 'done') {
            const mappedFields = file.steps.map?.done || file.done;
            progressSummaryText = mappedFields ? `${mappedFields} fields` : 'Done';
          } else if (file.status === 'failed') {
            progressSummaryText = file.message || 'Error occurred';
          } else if (file.status === 'running') {
            const stepName = PIPELINE_STEPS.find((s) => s.key === file.step)?.name || file.step;
            if (file.total) {
              progressSummaryText = `${stepName} ${file.done}/${file.total} ${file.unit}`;
            } else {
              progressSummaryText = `${stepName} in progress`;
            }
          } else {
            progressSummaryText = 'Queued';
          }

          return (
            <div
              key={file.file_id}
              id={`file-row-${file.file_id}`}
              style={{
                borderRadius: 8,
                border: isHighlighted
                  ? '2px solid var(--color-accent)'
                  : '1px solid var(--color-border-subtle)',
                background: isHighlighted ? 'var(--color-accent-light)' : 'var(--color-surface-2)',
                boxShadow: isHighlighted ? '0 0 0 3px var(--color-accent-muted)' : undefined,
                transition: 'all 0.2s ease',
                overflow: 'hidden',
              }}
            >
              {/* File Header Row */}
              <div
                style={{
                  padding: '10px 14px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 12,
                  cursor: 'pointer',
                  minHeight: 44,
                }}
                onClick={() => toggleExpand(file.file_id)}
                role="button"
                tabIndex={0}
                aria-expanded={isExpanded}
                aria-controls={`file-details-${file.file_id}`}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleExpand(file.file_id);
                  }
                }}
              >
                {/* Left: Icon + File Name */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, flex: 1 }}>
                  {getFileIcon(file.file_name)}
                  <span
                    style={{
                      fontWeight: 600,
                      fontSize: '0.875rem',
                      color: 'var(--color-text-primary)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {file.file_name}
                  </span>
                </div>

                {/* Right: Progress text + Status Chip + Expand Chevron + Retry */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
                  <span
                    style={{
                      fontSize: '0.8rem',
                      color: file.status === 'failed' ? 'var(--color-error)' : 'var(--color-text-secondary)',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {progressSummaryText}
                  </span>

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
                    {chipIcon}
                    <span>{chipText}</span>
                  </span>

                  {file.status === 'failed' && onRetryFile && (
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-danger"
                      style={{ minHeight: 44, minWidth: 44, padding: '4px 8px', display: 'flex', alignItems: 'center', gap: 4 }}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRetryFile(file.file_id);
                      }}
                      aria-label={`Retry processing file ${file.file_name}`}
                    >
                      <RotateCw size={12} />
                      <span>Retry file</span>
                    </button>
                  )}

                  <div style={{ color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center' }} aria-hidden="true">
                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </div>
                </div>
              </div>

              {/* Expandable Per-Step Mini Progress Bars */}
              {isExpanded && (
                <div
                  id={`file-details-${file.file_id}`}
                  style={{
                    padding: '12px 14px 14px',
                    borderTop: '1px solid var(--color-border)',
                    background: 'var(--color-surface)',
                  }}
                >
                  <div
                    style={{
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: 'var(--color-text-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                      marginBottom: 10,
                    }}
                  >
                    Per-Step Progress for {file.file_name}
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10 }}>
                    {PIPELINE_STEPS.map((s) => {
                      const stepData = file.steps[s.key];
                      const stepPct = stepData?.percent ?? (stepData?.status === 'done' ? 100 : 0);
                      const isStepRunning = stepData?.status === 'running';

                      return (
                        <div
                          key={s.key}
                          style={{
                            padding: '8px 10px',
                            borderRadius: 6,
                            background: 'var(--color-surface-2)',
                            border: '1px solid var(--color-border-subtle)',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                            <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                              {s.name}
                            </span>
                            <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                              {stepPct !== null ? `${stepPct}%` : '-'}
                            </span>
                          </div>

                          <StepProgressBar
                            percent={stepPct}
                            status={stepData?.status || 'default'}
                            isIndeterminate={isStepRunning && stepPct === null}
                            height={6}
                            ariaLabelledBy={`file-${file.file_id}-${s.key}`}
                            ariaValueText={`${s.name} for ${file.file_name}: ${stepPct}%`}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
