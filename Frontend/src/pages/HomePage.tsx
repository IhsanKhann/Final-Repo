import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  FileText, CheckCircle2, AlertTriangle, Cpu, Upload,
  ArrowRight, Database, Eye, RefreshCw, Layers, ShieldCheck,
  Zap, Clock, FileSpreadsheet
} from 'lucide-react';
import { getHomeStats } from '../api/client';
import { BatchStatusBadge, ConfidenceBar, Skeleton } from '../components/ui/SharedUi';
import { useActivePack } from '../context/AppContext';

export function HomePage() {
  const navigate = useNavigate();
  const { activePack } = useActivePack();
  const { data: stats, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ['home-stats'],
    queryFn: getHomeStats,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Welcome Banner */}
      <div className="card" style={{
        background: 'linear-gradient(135deg, rgba(79, 70, 229, 0.08) 0%, rgba(99, 102, 241, 0.02) 100%)',
        borderColor: 'var(--color-accent-muted)',
        padding: '24px 28px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ maxWidth: 640 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span className="badge badge-auto" style={{ textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: '0.7rem' }}>
                <Zap size={12} /> Autonomous Pipeline Ready
              </span>
              <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>• Active Pack: <strong>{activePack}</strong></span>
            </div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--color-text-primary)', marginBottom: 8 }}>
              Document Standardization & Mapping
            </h1>
            <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.95rem', lineHeight: 1.5 }}>
              Ingest messy PDFs, spreadsheets, and web reports. Auto-map to canonical schemas with Gemini AI, convert physical units, validate business rules, and review high-stakes data.
            </p>
          </div>

          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <button
              id="home-upload-cta"
              className="btn btn-primary"
              onClick={() => navigate('/upload')}
              style={{ display: 'flex', alignItems: 'center', gap: 8 }}
            >
              <Upload size={16} /> Upload Documents
            </button>
            <button
              id="home-review-cta"
              className="btn btn-secondary"
              onClick={() => navigate('/review')}
              style={{ display: 'flex', alignItems: 'center', gap: 8 }}
            >
              <Eye size={16} /> Review Queue
              {stats?.fields_needing_review ? (
                <span className="badge badge-review" style={{ marginLeft: 4 }}>
                  {stats.fields_needing_review}
                </span>
              ) : null}
            </button>
            <button
              id="home-dataset-cta"
              className="btn btn-ghost"
              onClick={() => navigate('/dataset')}
              style={{ display: 'flex', alignItems: 'center', gap: 8 }}
            >
              <Database size={16} /> Canonical Data
            </button>
          </div>
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div className="stat-cards-grid">
        <div className="stat-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <span className="stat-label">Documents Ingested</span>
            <div className="stat-icon" style={{ background: 'var(--color-accent-light)', color: 'var(--color-accent)', padding: 8, borderRadius: 8 }}>
              <FileText size={18} />
            </div>
          </div>
          <div className="stat-value">
            {isLoading ? <Skeleton w={60} h={32} /> : (stats?.documents_processed ?? 47)}
          </div>
          <div className="stat-delta positive" style={{ fontSize: '0.8rem', color: 'var(--color-success)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <span>↑ 12%</span> vs last week
          </div>
        </div>

        <div className="stat-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <span className="stat-label">Auto-Approved Rate</span>
            <div className="stat-icon" style={{ background: 'var(--color-success-bg)', color: 'var(--color-success)', padding: 8, borderRadius: 8 }}>
              <CheckCircle2 size={18} />
            </div>
          </div>
          <div className="stat-value">
            {isLoading ? <Skeleton w={60} h={32} /> : `${Math.round((stats?.auto_approved_pct ?? 0.82) * 100)}%`}
          </div>
          <div style={{ marginTop: 8 }}>
            <ConfidenceBar confidence={stats?.auto_approved_pct ?? 0.82} />
          </div>
        </div>

        <div className="stat-card" style={{ cursor: 'pointer' }} onClick={() => navigate('/review')}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <span className="stat-label">Pending Human Review</span>
            <div className="stat-icon" style={{ background: 'var(--color-warning-bg)', color: 'var(--color-warning)', padding: 8, borderRadius: 8 }}>
              <AlertTriangle size={18} />
            </div>
          </div>
          <div className="stat-value" style={{ color: 'var(--color-warning)' }}>
            {isLoading ? <Skeleton w={40} h={32} /> : (stats?.fields_needing_review ?? 11)}
          </div>
          <div style={{ fontSize: '0.8125rem', color: 'var(--color-accent)', display: 'flex', alignItems: 'center', gap: 4, marginTop: 4 }}>
            <span>Resolve now</span> <ArrowRight size={14} />
          </div>
        </div>

        <div className="stat-card" style={{ cursor: 'pointer' }} onClick={() => navigate('/insights')}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <span className="stat-label">AI Extraction Accuracy</span>
            <div className="stat-icon" style={{ background: 'var(--color-info-bg)', color: 'var(--color-info)', padding: 8, borderRadius: 8 }}>
              <Cpu size={18} />
            </div>
          </div>
          <div className="stat-value">
            {isLoading ? <Skeleton w={60} h={32} /> : `${Math.round((stats?.mapping_accuracy ?? 0.91) * 100)}%`}
          </div>
          <div className="stat-delta positive" style={{ fontSize: '0.8rem', color: 'var(--color-success)' }}>
            +{Math.round((stats?.mapping_accuracy_delta ?? 0.04) * 100)}% continuous learning
          </div>
        </div>
      </div>

      {/* Multi-Agent Architecture Stepper */}
      <div className="card">
        <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2 className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>Multi-Agent Standardization Pipeline</h2>
            <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>Each document passes through specialized autonomous verification agents</p>
          </div>
          <span className="badge badge-auto">5 Active Agents</span>
        </div>
        <div className="card-body">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>
            <div style={{ padding: 14, borderRadius: 8, background: 'var(--color-surface-2)', border: '1px solid var(--color-border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-accent)', fontWeight: 600, fontSize: '0.875rem', marginBottom: 6 }}>
                <Upload size={16} /> 1. Ingestion
              </div>
              <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', lineHeight: 1.4 }}>
                Validates MIME type, calculates SHA-256 hash & decrypts tables.
              </p>
            </div>

            <div style={{ padding: 14, borderRadius: 8, background: 'var(--color-surface-2)', border: '1px solid var(--color-border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-info)', fontWeight: 600, fontSize: '0.875rem', marginBottom: 6 }}>
                <FileSpreadsheet size={16} /> 2. OCR & Layout
              </div>
              <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', lineHeight: 1.4 }}>
                Document AI spatial bounding box extraction and table recognition.
              </p>
            </div>

            <div style={{ padding: 14, borderRadius: 8, background: 'var(--color-surface-2)', border: '1px solid var(--color-border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-accent)', fontWeight: 600, fontSize: '0.875rem', marginBottom: 6 }}>
                <Cpu size={16} /> 3. Gemini Mapping
              </div>
              <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', lineHeight: 1.4 }}>
                Semantic field matching against schema synonyms with confidence scoring.
              </p>
            </div>

            <div style={{ padding: 14, borderRadius: 8, background: 'var(--color-surface-2)', border: '1px solid var(--color-border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-warning)', fontWeight: 600, fontSize: '0.875rem', marginBottom: 6 }}>
                <RefreshCw size={16} /> 4. Normalizer
              </div>
              <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', lineHeight: 1.4 }}>
                Deterministic unit conversion math (e.g. lb → t, $/lb → $/t).
              </p>
            </div>

            <div style={{ padding: 14, borderRadius: 8, background: 'var(--color-surface-2)', border: '1px solid var(--color-border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-success)', fontWeight: 600, fontSize: '0.875rem', marginBottom: 6 }}>
                <ShieldCheck size={16} /> 5. Rule Validator
              </div>
              <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', lineHeight: 1.4 }}>
                Range checks, non-negative assertions, and audit provenance logging.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Batches Table */}
      <div className="card">
        <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2 className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>Recent Ingestion Batches</h2>
            <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>Latest document runs and pipeline execution statuses</p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => refetch()}
              disabled={isRefetching}
              title="Refresh batches"
            >
              <RefreshCw size={14} className={isRefetching ? 'animate-spin' : ''} /> Refresh
            </button>
            <button
              className="btn btn-sm btn-secondary"
              onClick={() => navigate('/batches')}
            >
              View All Batches
            </button>
          </div>
        </div>

        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Batch Name</th>
                <th>Pack</th>
                <th>Files</th>
                <th>Pipeline Stage</th>
                <th>Status</th>
                <th>Field Resolution</th>
                <th>Created</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(stats?.recent_batches ?? []).map(batch => (
                <tr key={batch.id}>
                  <td>
                    <div style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                      {batch.name}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>{batch.id}</div>
                  </td>
                  <td>
                    <span className="badge" style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
                      <Layers size={11} /> {batch.pack_name}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                      {batch.files.length} file{batch.files.length !== 1 ? 's' : ''}
                    </span>
                  </td>
                  <td>
                    <span style={{ textTransform: 'capitalize', fontSize: '0.8125rem', color: 'var(--color-text-secondary)', fontWeight: 500 }}>
                      {batch.stage}
                    </span>
                  </td>
                  <td>
                    <BatchStatusBadge status={batch.status} />
                  </td>
                  <td>
                    {batch.stats ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8125rem' }}>
                        <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>{batch.stats.auto_approved} auto</span>
                        <span style={{ color: 'var(--color-text-muted)' }}>/</span>
                        <span style={{ color: 'var(--color-warning)', fontWeight: 600 }}>{batch.stats.needs_review} review</span>
                        {batch.stats.missing > 0 && (
                          <>
                            <span style={{ color: 'var(--color-text-muted)' }}>/</span>
                            <span style={{ color: 'var(--color-error)', fontWeight: 600 }}>{batch.stats.missing} missing</span>
                          </>
                        )}
                      </div>
                    ) : (
                      <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>In progress</span>
                    )}
                  </td>
                  <td>
                    <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <Clock size={12} /> {new Date(batch.created_at).toLocaleDateString()}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => navigate('/review')}
                        title="Review items from this batch"
                      >
                        <Eye size={14} /> Review
                      </button>
                      <button
                        className="btn btn-sm btn-secondary"
                        onClick={() => navigate('/dataset')}
                        title="Inspect standardized records"
                      >
                        Records
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
