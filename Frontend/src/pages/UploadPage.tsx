import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  UploadCloud, FileText, FileSpreadsheet, Globe, CheckCircle2,
  AlertTriangle, ArrowRight, X, RefreshCw, Layers, ShieldCheck,
  Cpu, Zap, Play, Terminal, HelpCircle, AlertCircle, Ban
} from 'lucide-react';
import { getPacks, createBatch, connectBatchEvents, cancelBatch } from '../api/client';
import type { AgentEvent } from '../api/types';
import { useToast, useActivePack } from '../context/AppContext';

interface UploadItem {
  id: string;
  file?: File;
  name: string;
  type: string;
  size: number;
  status: 'Ready' | 'Uploading' | 'Processing' | 'Done' | 'Unsupported';
  progress: number;
  error?: string;
}

const SUPPORTED_EXTS = ['.pdf', '.xlsx', '.xls', '.csv', '.html', '.htm', '.txt'];

export function UploadPage() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const { activePack, setActivePack } = useActivePack();

  const [activeTab, setActiveTab] = useState<'files' | 'url'>('files');
  const [items, setItems] = useState<UploadItem[]>([
    { id: 'sample-1', name: 'rates_q3.xlsx', type: 'Excel', size: 204800, status: 'Ready', progress: 100 },
    { id: 'sample-2', name: 'filing.pdf', type: 'PDF (scan)', size: 1048576, status: 'Ready', progress: 100 },
  ]);
  const [reportUrl, setReportUrl] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentStage, setCurrentStage] = useState<string>('idle');
  const [agentLogs, setAgentLogs] = useState<AgentEvent[]>([]);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const logBottomRef = useRef<HTMLDivElement>(null);

  const { data: packs } = useQuery({
    queryKey: ['packs'],
    queryFn: getPacks,
  });

  const activePackObj = packs?.find(p => p.id === activePack) ?? packs?.[0];

  const validateAndAddFiles = (files: File[]) => {
    const newItems: UploadItem[] = files.map(file => {
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();
      const isSupported = SUPPORTED_EXTS.includes(ext);

      return {
        id: `file-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        file,
        name: file.name,
        type: ext === '.pdf' ? 'PDF' : ext.includes('xls') ? 'Excel' : ext === '.csv' ? 'CSV' : ext.includes('htm') ? 'HTML' : 'Text',
        size: file.size,
        status: isSupported ? 'Ready' : 'Unsupported',
        progress: isSupported ? 100 : 0,
        error: isSupported ? undefined : 'Unsupported format. Supported: CSV, XLSX, PDF, HTML, TXT.',
      };
    });

    setItems(prev => [...prev, ...newItems]);
  };

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
      validateAndAddFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndAddFiles(Array.from(e.target.files));
    }
  };

  const handleAddUrl = () => {
    if (!reportUrl.trim()) return;
    const item: UploadItem = {
      id: `url-${Date.now()}`,
      name: reportUrl.replace(/^https?:\/\//, ''),
      type: 'Web Report',
      size: 64000,
      status: 'Ready',
      progress: 100,
    };
    setItems(prev => [...prev, item]);
    setReportUrl('');
    addToast({ type: 'info', title: 'URL Added', message: 'Remote source queued for crawling.' });
  };

  const handleRemoveItem = (id: string) => {
    setItems(prev => prev.filter(item => item.id !== id));
  };

  const handleCancelRun = async () => {
    if (activeBatchId) {
      await cancelBatch(activeBatchId);
    }
    setIsProcessing(false);
    setCurrentStage('idle');
    addToast({ type: 'warning', title: 'Pipeline Cancelled', message: 'Ingestion batch was halted.' });
  };

  const handleStartPipeline = async () => {
    const validItems = items.filter(i => i.status !== 'Unsupported');
    if (validItems.length === 0) {
      addToast({
        type: 'warning',
        title: 'No Valid Documents',
        message: 'Please add at least one supported PDF, Excel, CSV, or HTML file.',
      });
      return;
    }

    setIsProcessing(true);
    setCurrentStage('ingest');
    setAgentLogs([]);

    try {
      const filesToUpload = validItems.map(i => i.file).filter(Boolean) as File[];
      const batch = await createBatch(
        { pack_id: activePack, url: reportUrl || undefined },
        filesToUpload
      );

      setActiveBatchId(batch.id);

      // Connect SSE stream
      connectBatchEvents(batch.id, (event: AgentEvent) => {
        setAgentLogs(prev => [...prev, event]);
        if (event.step) setCurrentStage(event.step);

        if (event.step === 'validate' && event.status === 'done') {
          setCurrentStage('ready');
          setIsProcessing(false);
          addToast({
            type: 'success',
            title: 'Standardization Ready',
            message: 'All fields mapped, converted and validated. Review Queue ready.',
          });
        }
      });
    } catch (err: any) {
      setIsProcessing(false);
      setCurrentStage('failed');
      addToast({
        type: 'error',
        title: 'Pipeline Error',
        message: err.message || 'Service returned an error.',
      });
    }
  };

  useEffect(() => {
    logBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentLogs]);

  const pipelineSteps = [
    { key: 'ingest', label: 'Ingest', desc: 'MIME validation' },
    { key: 'parse', label: 'Parse/OCR', desc: 'Document AI layout' },
    { key: 'map', label: 'Map fields', desc: 'Gemini reasoning' },
    { key: 'normalize', label: 'Normalize', desc: 'Unit math' },
    { key: 'validate', label: 'Validate', desc: 'Business rules' },
    { key: 'ready', label: 'Ready', desc: 'Human review' },
  ];

  const getStepIndex = (st: string) => {
    switch (st) {
      case 'ingest': return 0;
      case 'parse': return 1;
      case 'map': return 2;
      case 'normalize': return 3;
      case 'validate': return 4;
      case 'ready': return 5;
      default: return -1;
    }
  };

  const activeStepIdx = getStepIndex(currentStage);

  const hasUnsupported = items.some(i => i.status === 'Unsupported');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 980, margin: '0 auto' }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Ingest & Standardize Documents
        </h1>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
          Upload heterogeneous files. Our multi-agent system extracts fields, standardizes units, and prepares audit-ready data.
        </p>
      </div>

      {/* Target Schema Pack Card */}
      <div className="card" style={{ padding: '14px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Layers size={18} color="var(--color-accent)" />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                Target Schema Pack:
              </span>
              <div className="select-wrapper">
                <select
                  value={activePack}
                  onChange={e => setActivePack(e.target.value)}
                  style={{ fontSize: '0.85rem', padding: '4px 24px 4px 8px', fontWeight: 600 }}
                >
                  {(packs ?? []).map(p => (
                    <option key={p.id} value={p.id}>{p.name} {p.version}</option>
                  ))}
                </select>
              </div>
            </div>
            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
              {activePackObj?.description || 'Defines canonical fields, synonyms, unit multipliers & business constraints.'}
            </span>
          </div>
        </div>

        <button
          className="btn btn-ghost btn-sm"
          onClick={() => navigate('/schema')}
          style={{ fontSize: '0.8125rem', display: 'flex', alignItems: 'center', gap: 4 }}
        >
          <HelpCircle size={14} /> Configure Schema
        </button>
      </div>

      {/* Upload Box Card */}
      <div className="card">
        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
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
              padding: '36px 20px',
              textAlign: 'center',
              cursor: 'pointer',
              background: isDragging ? 'var(--color-accent-light)' : 'var(--color-surface-2)',
              transition: 'all 0.15s ease',
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
            <div style={{ display: 'inline-flex', padding: 12, borderRadius: '50%', background: 'var(--color-surface)', color: 'var(--color-accent)', marginBottom: 10, boxShadow: 'var(--shadow-sm)' }}>
              <UploadCloud size={28} />
            </div>
            <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
              Drop files here or <span style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>Browse</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', marginTop: 4 }}>
              Accepted formats: <strong>CSV, XLSX, PDF, HTML, TXT</strong>
            </div>
          </div>

          {/* URL Input */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>
              Or paste a page URL:
            </span>
            <input
              type="url"
              placeholder="https://example.com/reports/production-q3.pdf"
              value={reportUrl}
              onChange={e => setReportUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAddUrl(); }}
              style={{
                flex: 1,
                padding: '7px 12px',
                borderRadius: 6,
                border: '1px solid var(--color-border)',
                background: 'var(--color-surface)',
                fontSize: '0.85rem',
              }}
            />
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleAddUrl}
              disabled={!reportUrl.trim()}
            >
              Add
            </button>
          </div>

          {/* Files List Table */}
          {items.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>Type</th>
                      <th>Status & Progress</th>
                      <th style={{ width: 60, textAlign: 'right' }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map(item => (
                      <tr key={item.id} style={{ background: item.status === 'Unsupported' ? 'var(--color-error-bg)' : undefined }}>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            {item.type.includes('Excel') || item.type === 'CSV' ? (
                              <FileSpreadsheet size={16} color="var(--color-success)" />
                            ) : (
                              <FileText size={16} color="var(--color-accent)" />
                            )}
                            <div>
                              <div style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>
                                {item.name}
                              </div>
                              <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                                {(item.size / 1024).toFixed(1)} KB
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className="badge" style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', fontSize: '0.75rem' }}>
                            {item.type}
                          </span>
                        </td>
                        <td>
                          {item.status === 'Unsupported' ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--color-error)', fontSize: '0.8rem', fontWeight: 600 }}>
                              <AlertCircle size={14} />
                              <span>{item.error || 'Unsupported file.'}</span>
                            </div>
                          ) : (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span className="badge badge-auto" style={{ fontSize: '0.75rem' }}>
                                <CheckCircle2 size={12} /> {item.status}
                              </span>
                              <div className="progress-bar-track" style={{ width: 80, height: 6, background: 'var(--color-surface-2)', borderRadius: 4, overflow: 'hidden' }}>
                                <div style={{ width: `${item.progress}%`, height: '100%', background: 'var(--color-success)' }} />
                              </div>
                            </div>
                          )}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <button
                            className="btn btn-ghost btn-sm btn-icon"
                            onClick={() => handleRemoveItem(item.id)}
                            title={item.status === 'Unsupported' ? 'Remove unsupported file' : 'Remove file'}
                          >
                            <X size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Stepper action buttons */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--color-border)', paddingTop: 14 }}>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setItems([])}
              disabled={items.length === 0 || isProcessing}
            >
              Clear All
            </button>

            <button
              id="start-standardizing-btn"
              className="btn btn-primary"
              onClick={handleStartPipeline}
              disabled={isProcessing || items.filter(i => i.status !== 'Unsupported').length === 0}
              style={{ display: 'flex', alignItems: 'center', gap: 8 }}
            >
              {isProcessing ? (
                <>
                  <RefreshCw size={15} className="animate-spin" /> Standardizing…
                </>
              ) : (
                <>
                  Start standardizing <ArrowRight size={15} />
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Screen 3: Live Run Pipeline Stepper & SSE Agent Activity */}
      {(isProcessing || agentLogs.length > 0) && (
        <div className="card" style={{ borderColor: 'var(--color-accent-muted)' }}>
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Cpu size={18} color="var(--color-accent)" />
              <h2 className="card-title" style={{ fontSize: '1rem', fontWeight: 600 }}>
                Live Agent Execution
              </h2>
            </div>
            {isProcessing && (
              <button
                className="btn btn-sm btn-danger"
                onClick={handleCancelRun}
              >
                Cancel Run
              </button>
            )}
          </div>

          <div className="card-body">
            {/* Informational Callout */}
            <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', background: 'var(--color-info-bg)', padding: '8px 12px', borderRadius: 6, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Info size={16} color="var(--color-info)" style={{ flexShrink: 0 }} />
              <span>You can leave this page; we will notify you when review is ready.</span>
            </div>

            {/* Pipeline Stepper (6 steps) */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'relative', marginBottom: 24, padding: '0 6px' }}>
              {pipelineSteps.map((step, idx) => {
                const isPassed = activeStepIdx > idx || currentStage === 'ready';
                const isCurrent = activeStepIdx === idx && currentStage !== 'ready';

                return (
                  <div key={step.key} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', zIndex: 1, flex: 1 }}>
                    <div
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: '50%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: isPassed ? 'var(--color-success)' : isCurrent ? 'var(--color-accent)' : 'var(--color-surface-2)',
                        color: isPassed || isCurrent ? 'white' : 'var(--color-text-muted)',
                        border: `2px solid ${isPassed ? 'var(--color-success)' : isCurrent ? 'var(--color-accent)' : 'var(--color-border)'}`,
                        fontWeight: 600,
                        fontSize: '0.8rem',
                        transition: 'all 0.25s ease',
                      }}
                    >
                      {isPassed ? <Check size={16} /> : isCurrent ? <RefreshCw size={14} className="animate-spin" /> : idx + 1}
                    </div>
                    <span style={{ fontSize: '0.8rem', fontWeight: isCurrent ? 700 : 500, color: isCurrent ? 'var(--color-accent)' : 'var(--color-text-primary)', marginTop: 6 }}>
                      {step.label}
                    </span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
                      {step.desc}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Agent Activity Terminal */}
            <div
              style={{
                background: '#0a0d14',
                borderRadius: 8,
                border: '1px solid #1e2536',
                padding: '12px 14px',
                fontFamily: 'monospace',
                fontSize: '0.8rem',
                color: '#d1d5db',
                maxHeight: 200,
                overflowY: 'auto',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#9ca3af', marginBottom: 6, borderBottom: '1px solid #1e2536', paddingBottom: 6 }}>
                <Terminal size={14} /> Agent Activity Timeline (SSE Stream)
              </div>
              {agentLogs.length === 0 ? (
                <div style={{ color: '#6b7280', fontStyle: 'italic' }}>Initializing autonomous agents…</div>
              ) : (
                agentLogs.map((log, idx) => (
                  <div key={idx} style={{ display: 'flex', gap: 8, padding: '2px 0' }}>
                    <span style={{ color: '#6b7280' }}>{new Date(log.timestamp).toLocaleTimeString()}</span>
                    <span style={{ color: '#818cf8', fontWeight: 600 }}>[{log.agent}]</span>
                    <span style={{ color: log.status === 'done' ? '#34d399' : log.status === 'error' ? '#f87171' : '#fef08a' }}>
                      {log.message}
                    </span>
                  </div>
                ))
              )}
              <div ref={logBottomRef} />
            </div>

            {/* Ready Callout CTA */}
            {currentStage === 'ready' && (
              <div
                style={{
                  marginTop: 16,
                  padding: '14px 18px',
                  background: 'var(--color-success-bg)',
                  borderRadius: 8,
                  border: '1px solid var(--color-success-border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: 12,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <CheckCircle2 size={22} color="var(--color-success)" />
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>Standardization Complete</div>
                    <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)' }}>
                      Source fields extracted and ready for validation.
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 10 }}>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => navigate('/review')}
                  >
                    Open Review Screen <ArrowRight size={14} />
                  </button>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => navigate('/dataset')}
                  >
                    View Dataset
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
