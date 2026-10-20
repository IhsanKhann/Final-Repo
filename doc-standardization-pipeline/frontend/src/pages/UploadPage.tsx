import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  UploadCloud, FileText, FileSpreadsheet, Globe, CheckCircle2,
  AlertTriangle, ArrowRight, X, RefreshCw, Layers, ShieldCheck,
  Cpu, Zap, Play, Terminal, HelpCircle, AlertCircle, Ban,
  Info, Check
} from 'lucide-react';
import { getPacks, createBatch, connectBatchEvents, cancelBatch } from '../api/client';
import type { AgentEvent } from '../api/types';
import { useToast, useActivePack } from '../context/AppContext';
import { useBatchProgress } from '../hooks/useBatchProgress';
import { LiveAgentExecution } from '../components/execution/LiveAgentExecution';

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
  const [activeBatchId, setActiveBatchId] = useState<string | null>(() => {
    return sessionStorage.getItem('activeBatchId') || null;
  });

  const batchProgress = useBatchProgress(activeBatchId || undefined);
  const simulatorRef = useRef<any>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

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

    try {
      let filesToUpload = validItems.map(i => i.file).filter(Boolean) as File[];
      if (filesToUpload.length === 0) {
        // If sample items were selected without file attachments, generate real sample documents
        const sampleCsv = `lane_id,origin,destination,base_freight_rate,gross_weight,fuel_surcharge\nLANE-401,Chicago,Seattle,$1450.00 / load,44000 lbs,14.5% (?) fluctuating\nLANE-402,Houston,Atlanta,$980.00 / load,22000 lbs,12.0%`;
        const blob = new Blob([sampleCsv], { type: 'text/csv' });
        filesToUpload = [new File([blob], 'rates_q3.csv', { type: 'text/csv' })];
      }

      const batch = await createBatch(
        { pack_id: activePack, url: reportUrl || undefined },
        filesToUpload
      );

      setActiveBatchId(batch.id);
      sessionStorage.setItem('activeBatchId', batch.id);

      if (import.meta.env.VITE_USE_MOCK === 'true') {
        if (simulatorRef.current) simulatorRef.current.stop();
        const { startProgressSimulation } = await import('../mocks/progressSimulator');
        simulatorRef.current = startProgressSimulation(batch.id, (event) => {
          batchProgress.pushEvent(event);
        });
      }
    } catch (err: any) {
      setIsProcessing(false);
      addToast({
        type: 'error',
        title: 'Pipeline Error',
        message: err.message || 'Service returned an error.',
      });
    }
  };

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

      {/* Screen 3: Live Agent Execution with real-time per-step progress bars & activity timeline */}
      {(activeBatchId || isProcessing || batchProgress.state.status !== 'waiting') && (
        <LiveAgentExecution progress={batchProgress} />
      )}
    </div>
  );
}
