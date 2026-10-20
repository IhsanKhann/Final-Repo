import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Eye, AlertTriangle, ArrowRight, CheckCircle2,
  Filter, Search, CheckSquare, Square, Sparkles, Play
} from 'lucide-react';
import { getReviewQueue, bulkAcceptMappings } from '../api/client';
import { ConfidenceBar, StatusBadge, TableSkeleton } from '../components/ui/SharedUi';
import { useToast } from '../context/AppContext';
import type { ReviewQueueItem } from '../api/types';

export function ReviewQueuePage() {
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const { data: queueItems, isLoading, refetch } = useQuery({
    queryKey: ['review-queue'],
    queryFn: getReviewQueue,
  });

  // Sort queue by lowest confidence first
  const sortedItems = [...(queueItems ?? [])].sort((a, b) => a.confidence - b.confidence);

  const filteredItems = sortedItems.filter(item => {
    return (
      item.document_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.target_field.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (item.reason && item.reason.toLowerCase().includes(searchQuery.toLowerCase()))
    );
  });

  const handleToggleSelect = (mappingId: string) => {
    setSelectedIds(prev =>
      prev.includes(mappingId) ? prev.filter(id => id !== mappingId) : [...prev, mappingId]
    );
  };

  const handleSelectAll = () => {
    if (selectedIds.length === filteredItems.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(filteredItems.map(i => i.mapping_id));
    }
  };

  const handleOpenFirst = () => {
    if (filteredItems.length > 0) {
      navigate('/review');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 1040, margin: '0 auto' }}>
      {/* Header & Quick Action */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
              Cross-Document Review Queue
            </h1>
            <span className="badge badge-review">{filteredItems.length} Flagged</span>
          </div>
          <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
            Aggregated queue of low-confidence predictions, footnote ambiguities, and missing values awaiting human validation.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            id="open-first-review-btn"
            className="btn btn-primary btn-sm"
            onClick={handleOpenFirst}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Play size={14} /> Open First (Enter)
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => navigate('/review')}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Eye size={14} /> Document Split View
          </button>
        </div>
      </div>

      {/* Filter and Bulk Bar */}
      <div className="card" style={{ padding: '12px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 260 }}>
          <Search size={16} color="var(--color-text-muted)" />
          <input
            type="search"
            placeholder="Search by field, document, or flag reason…"
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

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleSelectAll}
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8125rem' }}
          >
            {selectedIds.length === filteredItems.length && filteredItems.length > 0 ? (
              <CheckSquare size={14} color="var(--color-accent)" />
            ) : (
              <Square size={14} />
            )}
            Select All
          </button>

          {selectedIds.length > 0 && (
            <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
              {selectedIds.length} selected
            </span>
          )}
        </div>
      </div>

      {/* Queue Table */}
      <div className="card">
        {isLoading ? (
          <TableSkeleton rows={4} cols={6} />
        ) : filteredItems.length === 0 ? (
          <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--color-text-muted)' }}>
            <CheckCircle2 size={32} color="var(--color-success)" style={{ margin: '0 auto 12px' }} />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
              All Flagged Fields Have Been Resolved!
            </h3>
            <p style={{ fontSize: '0.875rem', marginTop: 4 }}>
              The canonical dataset is standardized and verified for downstream export.
            </p>
          </div>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 40 }}></th>
                  <th>Source Document</th>
                  <th>Canonical Field</th>
                  <th>Extracted Label</th>
                  <th>Flag Reason / Anomaly</th>
                  <th style={{ width: 140 }}>Confidence</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map(item => {
                  const isChecked = selectedIds.includes(item.mapping_id);

                  return (
                    <tr
                      key={item.mapping_id}
                      style={{ cursor: 'pointer' }}
                      onClick={() => navigate('/review')}
                    >
                      <td onClick={e => { e.stopPropagation(); handleToggleSelect(item.mapping_id); }}>
                        {isChecked ? (
                          <CheckSquare size={16} color="var(--color-accent)" />
                        ) : (
                          <Square size={16} color="var(--color-text-muted)" />
                        )}
                      </td>
                      <td>
                        <span style={{ fontWeight: 600, color: 'var(--color-text-primary)', fontSize: '0.85rem' }}>
                          {item.document_name}
                        </span>
                        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>{item.batch_id}</div>
                      </td>
                      <td>
                        <strong style={{ color: 'var(--color-accent)' }}>{item.target_field}</strong>
                      </td>
                      <td>
                        <span style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
                          {item.source_label || '(None)'}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', color: 'var(--color-warning)' }}>
                          <AlertTriangle size={13} style={{ flexShrink: 0 }} />
                          <span>{item.reason || 'Confidence below threshold'}</span>
                        </div>
                      </td>
                      <td>
                        <ConfidenceBar confidence={item.confidence} />
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={e => {
                            e.stopPropagation();
                            navigate('/review');
                          }}
                          style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                        >
                          Open <ArrowRight size={13} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
