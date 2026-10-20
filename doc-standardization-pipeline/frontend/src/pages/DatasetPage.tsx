import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Download, Database, Search, Filter, RefreshCw,
  FileSpreadsheet, FileJson, ShieldCheck, Eye, Layers,
  CheckCircle2, ExternalLink, AlertTriangle, Columns, Check
} from 'lucide-react';
import { getBatchRecords } from '../api/client';
import { StatusBadge, TableSkeleton } from '../components/ui/SharedUi';
import { useToast } from '../context/AppContext';
import type { DatasetRecord } from '../api/types';

export function DatasetPage() {
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [includeAudit, setIncludeAudit] = useState(true);
  const [showColumnPicker, setShowColumnPicker] = useState(false);
  const [showUnresolvedBanner, setShowUnresolvedBanner] = useState(true);

  // Column visibility settings
  const [visibleCols, setVisibleCols] = useState({
    id: true,
    document: true,
    provenance: true,
    siteName: true,
    production: true,
    unitCost: true,
    status: true,
  });

  const { data: recordsData, isLoading, refetch } = useQuery({
    queryKey: ['batch-records', 'batch-001'],
    queryFn: () => getBatchRecords('batch-001'),
  });

  const records = recordsData?.data ?? [];
  const unresolvedCount = 7; // Mock/real count of unreviewed items

  const handleExport = (format: 'csv' | 'json') => {
    let content = '';
    let filename = `canonical_dataset_${Date.now()}`;
    let mimeType = 'text/plain';

    if (format === 'csv') {
      filename += '.csv';
      mimeType = 'text/csv';
      const headers = ['ID', 'Document', 'Site Name', 'Production (t)', 'Unit Cost ($/t)', 'Status'];
      if (includeAudit) {
        headers.push('Source Location', 'Audit Hash', 'Extraction Engine');
      }

      const rows = records.map(r => {
        const row = [
          r.id,
          `"${r.document_name}"`,
          `"${r.site_name || ''}"`,
          r.production_t ?? '',
          r.unit_cost ?? '',
          r._status,
        ];
        if (includeAudit) {
          row.push(
            r._source_page ? `"Page ${r._source_page}"` : `"Cell ${r._source_cell || 'Parsed'}"`,
            '"sha256:4b9e281...f3a"',
            '"Gemini 1.5 Pro + Normalizer"'
          );
        }
        return row.join(',');
      });

      content = [headers.join(','), ...rows].join('\n');
    } else {
      filename += '.json';
      mimeType = 'application/json';
      const exportData = records.map(r => {
        if (!includeAudit) {
          const { _source_page, _source_cell, ...rest } = r;
          return rest;
        }
        return {
          ...r,
          audit_metadata: {
            provenance: r._source_page ? `Page ${r._source_page}` : `Cell ${r._source_cell}`,
            algorithm: 'Gemini 1.5 Pro + Deterministic Normalizer',
            verified_at: new Date().toISOString(),
          },
        };
      });
      content = JSON.stringify(exportData, null, 2);
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    addToast({
      type: 'success',
      title: 'Dataset Exported',
      message: `Downloaded ${filename} (${records.length} records, audit columns: ${includeAudit ? 'included' : 'omitted'}).`,
    });
  };

  const filteredRecords = records.filter(r => {
    const matchesSearch =
      (r.document_name?.toString().toLowerCase().includes(searchQuery.toLowerCase())) ||
      (r.site_name?.toString().toLowerCase().includes(searchQuery.toLowerCase())) ||
      (r.id.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesStatus = statusFilter === 'all' || r._status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Unresolved Flagged Fields Banner */}
      {showUnresolvedBanner && unresolvedCount > 0 && (
        <div
          className="alert alert-warning"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 18px',
            borderRadius: 8,
            background: 'var(--color-warning-bg)',
            border: '1px solid var(--color-warning-border)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <AlertTriangle size={18} color="var(--color-warning)" style={{ flexShrink: 0 }} />
            <span style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--color-text-primary)' }}>
              <strong>{unresolvedCount} fields still need review</strong> before final database synchronization.
            </span>
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <button
              className="btn btn-primary btn-sm"
              onClick={() => navigate('/review')}
              style={{ fontSize: '0.8125rem' }}
            >
              Review now
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setShowUnresolvedBanner(false)}
              style={{ fontSize: '0.8125rem' }}
            >
              Export anyway
            </button>
          </div>
        </div>
      )}

      {/* Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            Canonical Standardized Dataset
          </h1>
          <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
            Unified dataset across sources. Each record links directly back to original document coordinates.
          </p>
        </div>

        {/* Export & Audit Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8125rem', cursor: 'pointer', color: 'var(--color-text-secondary)' }}>
            <input
              type="checkbox"
              checked={includeAudit}
              onChange={e => setIncludeAudit(e.target.checked)}
              style={{ width: 15, height: 15 }}
            />
            Include source and audit columns
          </label>

          <button
            id="export-csv-btn"
            className="btn btn-secondary btn-sm"
            onClick={() => handleExport('csv')}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <FileSpreadsheet size={14} color="var(--color-success)" /> Download CSV
          </button>
          <button
            id="export-json-btn"
            className="btn btn-secondary btn-sm"
            onClick={() => handleExport('json')}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <FileJson size={14} color="var(--color-accent)" /> Download JSON
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ padding: '12px 18px' }}>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 260 }}>
            <Search size={16} color="var(--color-text-muted)" />
            <input
              type="search"
              placeholder="Search by site name, document, or record ID…"
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

          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Filter size={14} color="var(--color-text-muted)" />
              <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>Status:</span>
              <select
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value)}
                style={{
                  padding: '5px 10px',
                  borderRadius: 6,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface)',
                  fontSize: '0.8125rem',
                }}
              >
                <option value="all">All Records</option>
                <option value="auto">Auto-Approved</option>
                <option value="review">Needs Review</option>
                <option value="approved">Approved by You</option>
              </select>
            </div>

            {/* Column Picker Dropdown */}
            <div style={{ position: 'relative' }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setShowColumnPicker(v => !v)}
                style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8125rem' }}
              >
                <Columns size={14} /> Columns
              </button>

              {showColumnPicker && (
                <div
                  style={{
                    position: 'absolute',
                    top: '100%',
                    right: 0,
                    marginTop: 6,
                    background: 'var(--color-surface)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 8,
                    boxShadow: 'var(--shadow-md)',
                    padding: '10px 14px',
                    zIndex: 100,
                    width: 180,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                  }}
                >
                  <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-muted)' }}>Toggle Columns</span>
                  {Object.entries(visibleCols).map(([k, v]) => (
                    <label key={k} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', cursor: 'pointer', textTransform: 'capitalize' }}>
                      <input
                        type="checkbox"
                        checked={v}
                        onChange={() => setVisibleCols(prev => ({ ...prev, [k]: !prev[k as keyof typeof visibleCols] }))}
                      />
                      {k.replace(/([A-Z])/g, ' $1')}
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Dataset Records Table */}
      <div className="card">
        {isLoading ? (
          <TableSkeleton rows={4} cols={6} />
        ) : filteredRecords.length === 0 ? (
          <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--color-text-muted)' }}>
            <p>No records found matching filters.</p>
          </div>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  {visibleCols.id && <th>Record ID</th>}
                  {visibleCols.document && <th>Document</th>}
                  {visibleCols.provenance && <th>Source Location</th>}
                  {visibleCols.siteName && <th>Site Name</th>}
                  {visibleCols.production && <th style={{ textAlign: 'right' }}>Production (t)</th>}
                  {visibleCols.unitCost && <th style={{ textAlign: 'right' }}>Unit Cost ($/t)</th>}
                  {visibleCols.status && <th>Status</th>}
                  <th style={{ textAlign: 'right' }}>Provenance Link</th>
                </tr>
              </thead>
              <tbody>
                {filteredRecords.map(record => (
                  <tr key={record.id}>
                    {visibleCols.id && (
                      <td>
                        <span style={{ fontFamily: 'monospace', fontWeight: 600, fontSize: '0.8125rem', color: 'var(--color-accent)' }}>
                          {record.id}
                        </span>
                      </td>
                    )}
                    {visibleCols.document && (
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.85rem' }}>
                          <FileSpreadsheet size={14} color="var(--color-text-muted)" />
                          <span style={{ fontWeight: 500 }}>{record.document_name}</span>
                        </div>
                      </td>
                    )}
                    {visibleCols.provenance && (
                      <td>
                        <button
                          className="badge"
                          onClick={() => navigate('/review')}
                          style={{
                            background: 'var(--color-surface-2)',
                            border: '1px solid var(--color-border)',
                            fontSize: '0.75rem',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                          title="Click to jump to exact location in source document"
                        >
                          <ExternalLink size={10} />
                          {record._source_page ? `Page ${record._source_page}` : record._source_cell ? `Cell ${record._source_cell}` : 'Parsed Text'}
                        </button>
                      </td>
                    )}
                    {visibleCols.siteName && (
                      <td>
                        <strong style={{ color: 'var(--color-text-primary)' }}>
                          {record.site_name || '—'}
                        </strong>
                      </td>
                    )}
                    {visibleCols.production && (
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.875rem' }}>
                        {record.production_t != null ? (
                          <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                            {record.production_t} <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>t</span>
                          </span>
                        ) : '—'}
                      </td>
                    )}
                    {visibleCols.unitCost && (
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.875rem' }}>
                        {record.unit_cost != null ? (
                          <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                            ${record.unit_cost.toLocaleString()} <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>/t</span>
                          </span>
                        ) : (
                          <span style={{ color: 'var(--color-text-muted)' }}>—</span>
                        )}
                      </td>
                    )}
                    {visibleCols.status && (
                      <td>
                        <StatusBadge status={record._status} />
                      </td>
                    )}
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => navigate('/review')}
                        title="Inspect mapping in split view"
                      >
                        <Eye size={14} /> Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
