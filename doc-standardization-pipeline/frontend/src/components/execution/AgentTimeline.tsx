import React, { useState, useEffect, useRef } from 'react';
import { Terminal, Pause, Play, Copy, Check } from 'lucide-react';
import type { LogEvent } from '../../api/types';

export interface AgentTimelineProps {
  logs: LogEvent[];
  onHighlightFile: (fileId: string | null) => void;
  activeFileIdHighlight: string | null;
}

export function AgentTimeline({
  logs,
  onHighlightFile,
  activeFileIdHighlight,
}: AgentTimelineProps) {
  const [autoScrollPaused, setAutoScrollPaused] = useState(false);
  const [copied, setCopied] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom unless paused
  useEffect(() => {
    if (!autoScrollPaused && scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [logs, autoScrollPaused]);

  const handleCopyLog = async () => {
    try {
      const text = logs
        .map(
          (l) =>
            `${new Date(l.ts).toLocaleTimeString()} [${l.agent}] [${l.level.toUpperCase()}] ${l.message}`
        )
        .join('\n');
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.warn('Copy log failed:', err);
    }
  };

  // Helper to extract file reference from a log line
  const extractFileRef = (log: LogEvent): string | null => {
    if (log.file_id) return log.file_id;
    if (log.file_name) return log.file_name;
    const msg = log.message.toLowerCase();
    if (msg.includes('rates_q3.xlsx') || msg.includes('rates_q3')) return 'f-rates';
    if (msg.includes('filing.pdf') || msg.includes('filing')) return 'f-filing';
    if (msg.includes('notes.html') || msg.includes('notes')) return 'f-notes';
    return null;
  };

  return (
    <div
      className="card agent-timeline-card"
      style={{
        background: '#0a0d14',
        borderRadius: 8,
        border: '1px solid #1e2536',
        padding: '12px 14px',
        color: '#d1d5db',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      {/* Header with Title and Controls */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 10,
          borderBottom: '1px solid #1e2536',
          paddingBottom: 8,
          marginBottom: 8,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#9ca3af', fontSize: '0.85rem' }}>
          <Terminal size={15} />
          <span style={{ fontWeight: 600 }}>Agent Activity Timeline (SSE Stream)</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Pause / Resume Auto-scroll Toggle */}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setAutoScrollPaused((p) => !p)}
            style={{
              minHeight: 44,
              padding: '4px 10px',
              fontSize: '0.75rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              background: autoScrollPaused ? '#374151' : '#1f2937',
              color: autoScrollPaused ? '#fef08a' : '#d1d5db',
              border: '1px solid #374151',
              borderRadius: 6,
            }}
            aria-pressed={autoScrollPaused}
            aria-label={autoScrollPaused ? 'Resume auto-scroll' : 'Pause auto-scroll'}
          >
            {autoScrollPaused ? <Play size={12} /> : <Pause size={12} />}
            <span>{autoScrollPaused ? 'Resume scroll' : 'Pause scroll'}</span>
          </button>

          {/* Copy Log Button */}
          <button
            type="button"
            className="btn btn-sm"
            onClick={handleCopyLog}
            style={{
              minHeight: 44,
              padding: '4px 10px',
              fontSize: '0.75rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              background: '#1f2937',
              color: '#d1d5db',
              border: '1px solid #374151',
              borderRadius: 6,
            }}
            aria-label="Copy log to clipboard"
          >
            {copied ? <Check size={12} color="#34d399" /> : <Copy size={12} />}
            <span>{copied ? 'Copied!' : 'Copy log'}</span>
          </button>
        </div>
      </div>

      {/* Log Stream Container */}
      <div
        ref={scrollContainerRef}
        role="log"
        aria-live="off"
        aria-label="Agent activity log lines"
        tabIndex={0}
        style={{
          maxHeight: 220,
          overflowY: 'auto',
          fontSize: '0.8rem',
          lineHeight: 1.5,
          paddingRight: 4,
          outline: 'none',
        }}
      >
        {logs.length === 0 ? (
          <div style={{ color: '#6b7280', fontStyle: 'italic', padding: '8px 0' }}>
            Initializing autonomous agents…
          </div>
        ) : (
          logs.map((log, idx) => {
            const fileRef = extractFileRef(log);
            const isClickable = Boolean(fileRef);
            const isHighlighted = fileRef && activeFileIdHighlight === fileRef;

            let levelColor = '#fef08a'; // default yellow/info
            if (log.level === 'success') levelColor = '#34d399';
            else if (log.level === 'error') levelColor = '#f87171';
            else if (log.level === 'warn') levelColor = '#fbbf24';

            return (
              <div
                key={idx}
                onClick={
                  isClickable
                    ? () => onHighlightFile(activeFileIdHighlight === fileRef ? null : fileRef)
                    : undefined
                }
                style={{
                  display: 'flex',
                  gap: 8,
                  padding: '3px 6px',
                  borderRadius: 4,
                  cursor: isClickable ? 'pointer' : 'default',
                  background: isHighlighted ? 'rgba(99, 102, 241, 0.25)' : 'transparent',
                  border: isHighlighted ? '1px solid rgba(99, 102, 241, 0.5)' : '1px solid transparent',
                  transition: 'background 0.15s ease',
                }}
                title={isClickable ? 'Click to highlight mentioned file' : undefined}
              >
                {/* Timestamp */}
                <span style={{ color: '#6b7280', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                  {new Date(log.ts).toLocaleTimeString()}
                </span>

                {/* Agent Tag */}
                <span style={{ color: '#818cf8', fontWeight: 600, flexShrink: 0 }}>
                  [{log.agent}]
                </span>

                {/* Log Message */}
                <span style={{ color: levelColor, flex: 1, wordBreak: 'break-word' }}>
                  {log.message}
                </span>

                {/* File Mention Indicator */}
                {isClickable && (
                  <span
                    style={{
                      fontSize: '0.7rem',
                      color: '#a5b4fc',
                      textDecoration: 'underline',
                      flexShrink: 0,
                      alignSelf: 'center',
                    }}
                  >
                    view file
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
