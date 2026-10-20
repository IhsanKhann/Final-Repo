import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  UploadCloud, FileText, FileSpreadsheet, Globe, CheckCircle2,
  AlertCircle, ArrowRight, X, RefreshCw, Layers, ShieldCheck,
  Cpu, Zap, Play, Terminal
} from 'lucide-react';
import { getPacks, createBatch, connectBatchEvents } from '../api/client';
import type { AgentEvent } from '../api/types';
import { useToast, useActivePack } from '../context/AppContext';

export function UploadPage() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const { activePack, setActivePack } = useActivePack();

  const [activeTab, setActiveTab] = useState<'files' | 'url'>('files');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [reportUrl, setReportUrl] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentStage, setCurrentStage] = useState<string>('idle');
  const [agentLogs, setAgentLogs] = useState<AgentEvent[]>([]);
  const [processedBatchId, setProcessedBatchId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const logBottomRef = useRef<HTMLDivElement>(null);

  const { data: packs } = useQuery({
    queryKey: ['packs'],
    queryFn: getPacks,
  });

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const filesArr = Array.from(e.dataTransfer.files);
      setSelectedFiles(prev => [...prev, ...filesArr]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const filesArr = Array.from(e.target.files);
      setSelectedFiles(prev => [...prev, ...filesArr]);
    }
  };

  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleStartPipeline = async () => {
    if (activeTab === 'files' && selectedFiles.length === 0) {
      addToast({
        type: 'warning',
        title: 'No files selected',
        message: 'Please attach at least one PDF, spreadsheet, or HTML document.',
      });
      return;
    }
    if (activeTab === 'url' && !reportUrl.trim()) {
      addToast({
        type: 'warning',
        title: 'URL required',
        message: 'Please provide a valid remote document URL.',
      });
      return;
    }

    setIsProcessing(true);
    setCurrentStage('uploading');
    setAgentLogs([]);
    setProcessedBatchId(null);

    try {
      const batch = await createBatch(
        {
          pack_id: activePack,
          url: activeTab === 'url' ? reportUrl : undefined,
        },
        selectedFiles,
        pct => setUploadProgress(pct)
      );

      setProcessedBatchId(batch.id);
      setCurrentStage('processing');

      // Listen to pipeline events
      connectBatchEvents(batch.id, (event: AgentEvent) => {
        setAgentLogs(prev => [...prev, event]);
        if (event.step) setCurrentStage(event.step);
        if (event.step === 'validate' && event.status === 'done') {
          setCurrentStage('completed');
          setIsProcessing(false);
          addToast({
            type: 'success',
            title: 'Pipeline Completed',
            message: `Batch "${batch.name}" processed successfully. Ready for review.`,
          });
        }
      });
    } catch (err: any) {
      setIsProcessing(false);
      setCurrentStage('failed');
      addToast({
        type: 'error',
        title: 'Pipeline Error',
        message: err.message || 'Failed to process documents.',
      });
    }
  };

  useEffect(() => {
    logBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentLogs]);

  const stages = [
    { key: 'ingest', label: 'Ingest', desc: 'MIME & Hashing' },
    { key: 'parse', label: 'OCR & Layout', desc: 'Document AI' },
    { key: 'map', label: 'Gemini Mapping', desc: 'Semantic Extraction' },
    { key: 'normalize', label: 'Normalize', desc: 'Unit Conversion' },
    { key: 'validate', label: 'Validate', desc: 'Business Rules' },
  ];

  const getStageIndex = (stage: string) => {
    switch (stage) {
      case 'ingest': return 0;
      case 'parse': return 1;
      case 'map': return 2;
      case 'normalize': return 3;
      case 'validate': return 4;
      case 'completed': return 5;
      default: return -1;
    }
  };

  const activeStageIdx = getStageIndex(currentStage);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 1040, margin: '0 auto' }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Ingest & Standardize Documents
        </h1>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
          Upload heterogeneous PDFs, financial disclosures, rate sheets or web tables for automated Gemini mapping.
        </p>
      </div>

      {/* Target Schema Pack Selector */}
      <div className="card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ background: 'var(--color-accent-light)', color: 'var(--color-accent)', padding: 8, borderRadius: 8 }}>
              <Layers size={18} />
            </div>
            <div>
              <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                Target Canonical Schema Pack
              </div>
              <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                Defines target columns, required fields, accepted units, and business rules.
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            {(packs ?? []).map(p => (
              <button
                key={p.id}
                type="button"
                className={`btn btn-sm ${activePack === p.id ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setActivePack(p.id)}
              >
                {p.name} {p.version}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Upload Box Card */}
      <div className="card">
        {/* Source Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--color-border)', padding: '0 16px' }}>
          <button
            className="tab-button"
            style={{
              padding: '14px 18px',
              border: 'none',
              background: 'transparent',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
              color: activeTab === 'files' ? 'var(--color-accent)' : 'var(--color-text-muted)',
              borderBottom: activeTab === 'files' ? '2px solid var(--color-accent)' : '2px solid transparent',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
            onClick={() => setActiveTab('files')}
          >
            <FileText size={16} /> File Upload (PDF, XLSX, CSV, HTML)
          </button>
          <button
            className="tab-button"
            style={{
              padding: '14px 18px',
              border: 'none',
              background: 'transparent',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
              color: activeTab === 'url' ? 'var(--color-accent)' : 'var(--color-text-muted)',
              borderBottom: activeTab === 'url' ? '2px solid var(--color-accent)' : '2px solid transparent',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
            onClick={() => setActiveTab('url')}
          >
            <Globe size={16} /> Web Report URL
          </button>
        </div>

        <div className="card-body">
          {activeTab === 'files' ? (
            <div>
              {/* Dropzone */}
              <div
                className={`dropzone ${isDragging ? 'dropzone-active' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                style={{
                  border: `2px dashed ${isDragging ? 'var(--color-accent)' : 'var(--color-border)'}`,
                  borderRadius: 12,
                  padding: '40px 20px',
                  textAlign: 'center',
                  cursor: 'pointer',
                  background: isDragging ? 'var(--color-accent-light)' : 'var(--color-surface-2)',
                  transition: 'all 0.2s ease',
                }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.xlsx,.xls,.csv,.html,.htm,.txt"
                  style={{ display: 'none' }}
                  onChange={handleFileChange}
                />
                <div style={{ display: 'inline-flex', padding: 14, borderRadius: '50%', background: 'var(--color-surface)', color: 'var(--color-accent)', marginBottom: 12, boxShadow: 'var(--shadow-sm)' }}>
                  <UploadCloud size={32} />
                </div>
                <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                  Drag & drop source documents here
                </div>
                <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 4 }}>
                  Supports PDF scans, multi-tab Excel workbooks, CSV files, and HTML tables (up to 50MB each)
                </p>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  style={{ marginTop: 14 }}
                  onClick={e => { e.stopPropagation(); fileInputRef.current?.click(); }}
                >
                  Browse Files
                </button>
              </div>

              {/* Selected Files List */}
              {selectedFiles.length > 0 && (
                <div style={{ marginTop: 18 }}>
                  <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 8, textTransform: 'uppercase' }}>
                    Selected Documents ({selectedFiles.length})
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {selectedFiles.map((file, idx) => (
                      <div
                        key={idx}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '10px 14px',
                          background: 'var(--color-surface-2)',
                          borderRadius: 8,
                          border: '1px solid var(--color-border)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                          {file.name.endsWith('.xlsx') || file.name.endsWith('.csv') ? (
                            <FileSpreadsheet size={18} color="var(--color-success)" />
                          ) : (
                            <FileText size={18} color="var(--color-accent)" />
                          )}
                          <div>
                            <div style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--color-text-primary)' }}>
                              {file.name}
                            </div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                              {(file.size / 1024).toFixed(1)} KB • {file.type || 'Document'}
                            </div>
                          </div>
                        </div>

                        <button
                          type="button"
                          className="btn btn-ghost btn-sm btn-icon"
                          onClick={() => removeFile(idx)}
                          disabled={isProcessing}
                        >
                          <X size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div style={{ padding: '12px 0' }}>
              <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                Report Document or Filing URL
              </label>
              <input
                type="url"
                placeholder="https://example-mining-corp.com/reports/q3-2026-production.pdf"
                value={reportUrl}
                onChange={e => setReportUrl(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface)',
                  fontSize: '0.9rem',
                }}
              />
              <p style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginTop: 6 }}>
                Our ingestion crawler will securely fetch the page, resolve redirections, and pass to the parser.
              </p>
            </div>
          )}

          {/* Action Button */}
          <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
            <button
              id="start-pipeline-btn"
              className="btn btn-primary"
              disabled={isProcessing || (activeTab === 'files' ? selectedFiles.length === 0 : !reportUrl.trim())}
              onClick={handleStartPipeline}
              style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 160, justifyContent: 'center' }}
            >
              {isProcessing ? (
                <>
                  <RefreshCw size={16} className="animate-spin" /> Processing Pipeline…
                </>
              ) : (
                <>
                  <Play size={16} /> Run Pipeline
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Live Pipeline Stepper & Event Timeline (Visible during or after processing) */}
      {(isProcessing || agentLogs.length > 0) && (
        <div className="card" style={{ borderColor: 'var(--color-accent-muted)' }}>
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Cpu size={18} color="var(--color-accent)" />
              <h2 className="card-title" style={{ fontSize: '1rem', fontWeight: 600 }}>Autonomous Pipeline Execution</h2>
            </div>
            {currentStage === 'completed' && (
              <span className="badge badge-auto">All Stages Complete</span>
            )}
          </div>

          <div className="card-body">
            {/* Stepper */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'relative', marginBottom: 24, padding: '0 8px' }}>
              {stages.map((st, idx) => {
                const isPassed = activeStageIdx > idx || currentStage === 'completed';
                const isCurrent = activeStageIdx === idx && currentStage !== 'completed';

                return (
                  <div key={st.key} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', zIndex: 1, flex: 1 }}>
                    <div
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: '50%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: isPassed ? 'var(--color-success)' : isCurrent ? 'var(--color-accent)' : 'var(--color-surface-2)',
                        color: isPassed || isCurrent ? 'white' : 'var(--color-text-muted)',
                        border: `2px solid ${isPassed ? 'var(--color-success)' : isCurrent ? 'var(--color-accent)' : 'var(--color-border)'}`,
                        fontWeight: 600,
                        fontSize: '0.875rem',
                        transition: 'all 0.3s ease',
                      }}
                    >
                      {isPassed ? <CheckCircle2 size={18} /> : isCurrent ? <RefreshCw size={16} className="animate-spin" /> : idx + 1}
                    </div>
                    <span style={{ fontSize: '0.8125rem', fontWeight: isCurrent ? 700 : 500, color: isCurrent ? 'var(--color-accent)' : 'var(--color-text-primary)', marginTop: 6 }}>
                      {st.label}
                    </span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
                      {st.desc}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Live Terminal Agent Activity Feed */}
            <div style={{
              background: '#0a0d14',
              borderRadius: 8,
              border: '1px solid #1e2536',
              padding: '14px 16px',
              fontFamily: 'monospace',
              fontSize: '0.8125rem',
              color: '#d1d5db',
              maxHeight: 220,
              overflowY: 'auto',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#9ca3af', marginBottom: 8, borderBottom: '1px solid #1e2536', paddingBottom: 6 }}>
                <Terminal size={14} /> Agent Stream Protocol (SSE)
              </div>
              {agentLogs.length === 0 ? (
                <div style={{ color: '#6b7280', fontStyle: 'italic' }}>Waiting for agent task dispatch…</div>
              ) : (
                agentLogs.map((log, idx) => (
                  <div key={idx} style={{ display: 'flex', gap: 10, padding: '3px 0' }}>
                    <span style={{ color: '#6b7280' }}>
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                    <span style={{ color: '#818cf8', fontWeight: 600 }}>
                      [{log.agent}]
                    </span>
                    <span style={{ color: log.status === 'done' ? '#34d399' : log.status === 'error' ? '#f87171' : '#fef08a' }}>
                      {log.message}
                    </span>
                  </div>
                ))
              )}
              <div ref={logBottomRef} />
            </div>

            {/* Completion Actions */}
            {currentStage === 'completed' && (
              <div style={{
                marginTop: 20,
                padding: '16px 20px',
                background: 'var(--color-success-bg)',
                borderRadius: 8,
                border: '1px solid var(--color-success-border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 12,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <CheckCircle2 size={24} color="var(--color-success)" />
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>Batch Processed Successfully</div>
                    <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)' }}>
                      Extracted fields are ready for human verification and canonical export.
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 10 }}>
                  <button
                    className="btn btn-primary"
                    onClick={() => navigate('/review')}
                    style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                  >
                    Open Review Queue <ArrowRight size={16} />
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => navigate('/dataset')}
                  >
                    View in Dataset
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
