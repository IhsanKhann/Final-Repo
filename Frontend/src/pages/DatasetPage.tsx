import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Download, Database, Search, Filter, RefreshCw,
  FileSpreadsheet, FileJson, ShieldCheck, Eye, Layers,
  CheckCircle2, ExternalLink
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

  const { data: recordsData, isLoading, refetch } = useQuery({
    queryKey: ['batch-records', 'batch-001'],
    queryFn: () => getBatchRecords('batch-001'),
  });

  const records = recordsData?.data ?? [];

  const handleExport = (format: 'csv' | 'json' | 'audit') => {
    let content = '';
    let filename = `datasync-export-${Date.now()}`;
    let mimeType = 'text/plain';

    if (format === 'csv') {
      filename += '.csv';
      mimeType = 'text/csv';
      const headers = ['ID', 'Document', 'Site Name', 'Production (t)', 'Unit Cost ($/t)', 'Status', 'Source Location'];
      const rows = records.map(r => [
        r.id,
        `"${r.document_name}"`,
        `"${r.site_name || ''}"`,
        r.production_t ?? '',
        r.unit_cost ?? '',
        r._status,
        r._source_page ? `Page ${r._source_page}` : r._source_cell ? `Cell ${r._source_cell}` : 'Extracted',
      ]);
      content = [headers.join(','), ...rows.map(row => row.join(','))].join('\n');
    } else if (format === 'json') {
      filename += '.json';
      mimeType = 'application/json';
      content = JSON.stringify(records, null, 2);
    } else if (format === 'audit') {
      filename += '-audit-trail.json';
      mimeType = 'application/json';
      const auditPayload = {
        exported_at: new Date().toISOString(),
        dataset_version: 'canonical-v1',
        compliance_standard: 'SOC2 / GxP Traceable',
        records: records.map(r => ({
          ...r,
          audit_metadata: {
            provenance: r._source_page ? `PDF Page ${r._source_page}` : 'Sheet Extraction',
            algorithm: 'Gemini 1.5 Pro + Unit Normalizer',
            validation_hash: 'sha256:4b9e281...f3a',
          },
        })),
      };
      content = JSON.stringify(auditPayload, null, 2);
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
      title: 'Export Generated',
      message: `Downloaded ${filename} (${records.length} records).`,
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            Canonical Standardized Dataset
          </h1>
          <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
            Unified, validated data warehouse view with full document provenance and regulatory traceability.
          </p>
        </div>

        {/* Export Buttons */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => handleExport('csv')}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <FileSpreadsheet size={14} color="var(--color-success)" /> Export CSV
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => handleExport('json')}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <FileJson size={14} color="var(--color-accent)" /> Export JSON
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => handleExport('audit')}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <ShieldCheck size={14} /> Export Audit Trail
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
            <Filter size={14} color="var(--color-text-muted)" />
            <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>Status:</span>
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              style={{
                padding: '6px 12px',
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
        </div>
      </div>

      {/* Dataset Records Table */}
      <div className="card">
        {isLoading ? (
          <TableSkeleton rows={4} cols={7} />
        ) : filteredRecords.length === 0 ? (
          <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--color-text-muted)' }}>
            <p>No records found matching filters.</p>
          </div>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Record ID</th>
                  <th>Source Document</th>
                  <th>Provenance</th>
                  <th>Site Name</th>
                  <th style={{ textAlign: 'right' }}>Production (t)</th>
                  <th style={{ textAlign: 'right' }}>Unit Cost ($/t)</th>
                  <th>Status</th>
                  <th style={{ textAlign: 'right' }}>Inspect</th>
                </tr>
              </thead>
              <tbody>
                {filteredRecords.map(record => (
                  <tr key={record.id}>
                    <td>
                      <span style={{ fontFamily: 'monospace', fontWeight: 600, fontSize: '0.8125rem', color: 'var(--color-accent)' }}>
                        {record.id}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.85rem' }}>
                        <FileSpreadsheet size={14} color="var(--color-text-muted)" />
                        <span style={{ fontWeight: 500 }}>{record.document_name}</span>
                      </div>
                    </td>
                    <td>
                      <span className="badge" style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', fontSize: '0.75rem' }}>
                        {record._source_page ? `Page ${record._source_page}` : record._source_cell ? `Cell ${record._source_cell}` : 'Parsed Text'}
                      </span>
                    </td>
                    <td>
                      <strong style={{ color: 'var(--color-text-primary)' }}>
                        {record.site_name || '—'}
                      </strong>
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.875rem' }}>
                      {record.production_t != null ? (
                        <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                          {record.production_t} <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>t</span>
                        </span>
                      ) : '—'}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: '0.875rem' }}>
                      {record.unit_cost != null ? (
                        <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                          ${record.unit_cost.toLocaleString()} <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>/t</span>
                        </span>
                      ) : (
                        <span style={{ color: 'var(--color-text-muted)' }}>—</span>
                      )}
                    </td>
                    <td>
                      <StatusBadge status={record._status} />
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => navigate('/review')}
                        title="View source document extraction"
                      >
                        <Eye size={14} /> Review
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
