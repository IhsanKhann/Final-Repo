import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Layers, Search, Filter, RefreshCw, Eye, Database,
  FileText, Clock, CheckCircle2, AlertTriangle, XCircle,
  Upload, X, ArrowUpDown
} from 'lucide-react';
import { getBatches, cancelBatch, getPacks } from '../api/client';
import { BatchStatusBadge, TableSkeleton } from '../components/ui/SharedUi';
import { useToast } from '../context/AppContext';
import type { Batch } from '../api/types';

export function BatchesPage() {
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedPackFilter, setSelectedPackFilter] = useState('all');
  const [selectedStatusFilter, setSelectedStatusFilter] = useState('all');
  const [selectedBatchForModal, setSelectedBatchForModal] = useState<Batch | null>(null);

  const { data: packs } = useQuery({ queryKey: ['packs'], queryFn: getPacks });
  const { data: batches, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ['batches'],
    queryFn: getBatches,
  });

  const handleCancelBatch = async (batchId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await cancelBatch(batchId);
      addToast({
        type: 'info',
        title: 'Batch Cancelled',
        message: `Batch ${batchId} was successfully cancelled.`,
      });
      refetch();
    } catch (err: any) {
      addToast({
        type: 'error',
        title: 'Cancellation Failed',
        message: err.message,
      });
    }
  };

  const filteredBatches = (batches ?? []).filter(b => {
    const matchesSearch = b.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      b.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      b.pack_name.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesPack = selectedPackFilter === 'all' || b.pack_id === selectedPackFilter;
    const matchesStatus = selectedStatusFilter === 'all' || b.status === selectedStatusFilter;

    return matchesSearch && matchesPack && matchesStatus;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            Batch Execution History
          </h1>
          <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
            Monitor document ingestion runs, pipeline execution progress, and field resolution metrics.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => refetch()}
            disabled={isRefetching}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <RefreshCw size={14} className={isRefetching ? 'animate-spin' : ''} /> Refresh
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => navigate('/upload')}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Upload size={14} /> New Batch
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ padding: '14px 18px' }}>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 260 }}>
            <Search size={16} color="var(--color-text-muted)" />
            <input
              type="search"
              placeholder="Filter by batch name, ID, or pack…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                border: 'none',
                background: 'transparent',
                outline: 'none',
                fontSize: '0.875rem',
                color: 'var(--color-text-primary)',
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Filter size={14} color="var(--color-text-muted)" />
              <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>Pack:</span>
              <select
                value={selectedPackFilter}
                onChange={e => setSelectedPackFilter(e.target.value)}
                style={{
                  padding: '6px 12px',
                  borderRadius: 6,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface)',
                  fontSize: '0.8125rem',
                }}
              >
                {/* Packs come from the server. This list used to be hardcoded as Mining,
                    Shipping and Finance — none of which exist on any server, so the
                    filter offered three fictional options and silently matched nothing. */}
                <option value="all">All Packs</option>
                {packs?.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>Status:</span>
              <select
                value={selectedStatusFilter}
                onChange={e => setSelectedStatusFilter(e.target.value)}
                style={{
                  padding: '6px 12px',
                  borderRadius: 6,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface)',
                  fontSize: '0.8125rem',
                }}
              >
                <option value="all">All Statuses</option>
                <option value="done">Done</option>
                <option value="running">Running</option>
                <option value="pending">Pending</option>
                <option value="failed">Failed</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* Batches Table */}
      <div className="card">
        {isLoading ? (
          <TableSkeleton rows={5} cols={7} />
        ) : filteredBatches.length === 0 ? (
          /* Two different nothings. "No results for your filter" and "you have not run
             anything yet" need different words and different actions: the first asks you
             to widen the filter, the second asks you to upload. Showing the filter message
             on a first visit tells a new user their filter is wrong when they have not set
             one, and offers them nothing to do. */
          <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--color-text-muted)' }}>
            {(batches?.length ?? 0) === 0 ? (
              <>
                <p style={{ fontSize: '1rem', color: 'var(--color-text-primary)', fontWeight: 600, marginBottom: 6 }}>
                  No documents processed yet
                </p>
                <p style={{ fontSize: '0.875rem', marginBottom: 18 }}>
                  Upload PDFs, spreadsheets, HTML pages or narrative text and they will be
                  standardized against the active schema pack.
                </p>
                <button className="btn btn-primary btn-sm" onClick={() => navigate('/upload')}>
                  Upload documents
                </button>
              </>
            ) : (
              <>
                <p style={{ fontSize: '0.95rem', marginBottom: 12 }}>
                  No batches match the current filters — {batches?.length} exist in total.
                </p>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => { setSelectedPackFilter('all'); setSelectedStatusFilter('all'); }}
                >
                  Clear filters
                </button>
              </>
            )}
          </div>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Batch Name</th>
                  <th>Schema Pack</th>
                  <th>Files Included</th>
                  <th>Stage</th>
                  <th>Status</th>
                  <th>Resolution Breakdown</th>
                  <th>Created At</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredBatches.map(batch => (
                  <tr
                    key={batch.id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setSelectedBatchForModal(batch)}
                  >
                    <td>
                      <div style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                        {batch.name}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', fontFamily: 'monospace' }}>
                        {batch.id}
                      </div>
                    </td>
                    <td>
                      <span className="badge" style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
                        <Layers size={11} /> {batch.pack_name}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8125rem' }}>
                        <FileText size={14} color="var(--color-accent)" />
                        <span>{batch.files.length} file{batch.files.length !== 1 ? 's' : ''}</span>
                      </div>
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
                          <span style={{ color: 'var(--color-success)', fontWeight: 600 }} title="Auto-approved">
                            {batch.stats.auto_approved} auto
                          </span>
                          <span style={{ color: 'var(--color-text-muted)' }}>/</span>
                          <span style={{ color: 'var(--color-warning)', fontWeight: 600 }} title="Needs review">
                            {batch.stats.needs_review} review
                          </span>
                          {batch.stats.missing > 0 && (
                            <>
                              <span style={{ color: 'var(--color-text-muted)' }}>/</span>
                              <span style={{ color: 'var(--color-error)', fontWeight: 600 }} title="Missing required">
                                {batch.stats.missing} missing
                              </span>
                            </>
                          )}
                        </div>
                      ) : (
                        <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>Processing</span>
                      )}
                    </td>
                    <td>
                      <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
                        <Clock size={12} />
                        {new Date(batch.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }} onClick={e => e.stopPropagation()}>
                        <button
                          className="btn btn-sm btn-ghost"
                          onClick={() => navigate('/review')}
                          title="Review mappings"
                        >
                          <Eye size={14} /> Review
                        </button>
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => navigate('/dataset')}
                          title="View canonical records"
                        >
                          <Database size={14} /> Data
                        </button>
                        {batch.status === 'running' && (
                          <button
                            className="btn btn-sm btn-danger"
                            onClick={e => handleCancelBatch(batch.id, e)}
                            title="Cancel batch"
                          >
                            Cancel
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Batch Details Modal */}
      {selectedBatchForModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 16,
          }}
          onClick={() => setSelectedBatchForModal(null)}
        >
          <div
            className="card"
            style={{ width: '100%', maxWidth: 600, maxHeight: '90vh', overflowY: 'auto' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h2 className="card-title" style={{ fontSize: '1.1rem' }}>{selectedBatchForModal.name}</h2>
                <span style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--color-text-muted)' }}>
                  ID: {selectedBatchForModal.id}
                </span>
              </div>
              <button
                className="btn btn-ghost btn-sm btn-icon"
                onClick={() => setSelectedBatchForModal(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                <div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Target Schema</span>
                  <div style={{ fontWeight: 600, fontSize: '0.875rem' }}>{selectedBatchForModal.pack_name}</div>
                </div>
                <div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Status / Stage</span>
                  <div><BatchStatusBadge status={selectedBatchForModal.status} /></div>
                </div>
              </div>

              <div>
                <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                  Enclosed Source Documents ({selectedBatchForModal.files.length})
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                  {selectedBatchForModal.files.map(file => (
                    <div
                      key={file.id}
                      style={{
                        padding: '10px 14px',
                        background: 'var(--color-surface-2)',
                        borderRadius: 8,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <FileText size={16} color="var(--color-accent)" />
                        <div>
                          <div style={{ fontSize: '0.875rem', fontWeight: 500 }}>{file.name}</div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                            {(file.size / 1024).toFixed(1)} KB • {file.type}
                          </div>
                        </div>
                      </div>
                      <span className="badge badge-auto">{file.status}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 12 }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => {
                    setSelectedBatchForModal(null);
                    navigate('/dataset');
                  }}
                >
                  View Canonical Records
                </button>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    setSelectedBatchForModal(null);
                    navigate('/review');
                  }}
                >
                  Open Review Screen
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
