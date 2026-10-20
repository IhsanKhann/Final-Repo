import React, { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Check, X, Edit3, ChevronRight, ChevronLeft, AlertTriangle,
  CheckCircle2, FileText, ArrowRight, Sparkles, Filter,
  Maximize2, ZoomIn, ZoomOut, RotateCcw, Info
} from 'lucide-react';
import { getDocumentMappings, patchMapping, bulkAcceptMappings } from '../api/client';
import type { Mapping, MappingStatus } from '../api/types';
import { ConfidenceBar, StatusBadge, Skeleton } from '../components/ui/SharedUi';
import { useToast, useUndo } from '../context/AppContext';

export function ReviewPage() {
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const { pushUndo } = useUndo();

  const [activeDocId, setActiveDocId] = useState('doc-001');
  const [selectedMappingId, setSelectedMappingId] = useState<string | null>('m2');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [editingMappingId, setEditingMappingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [editUnit, setEditUnit] = useState('');
  const [docPage, setDocPage] = useState(3);

  const { data: mappings, isLoading, refetch } = useQuery({
    queryKey: ['mappings', activeDocId],
    queryFn: () => getDocumentMappings(activeDocId),
  });

  const activeMapping = (mappings ?? []).find(m => m.id === selectedMappingId) ?? mappings?.[0];

  // Set initial selected mapping when loaded
  useEffect(() => {
    if (mappings && mappings.length > 0 && !selectedMappingId) {
      const firstReview = mappings.find(m => m.status === 'review') || mappings[0];
      setSelectedMappingId(firstReview.id);
    }
  }, [mappings, selectedMappingId]);

  // Sync doc page to mapping location if available
  useEffect(() => {
    if (activeMapping?.source_location?.type === 'pdf') {
      setDocPage(activeMapping.source_location.page);
    }
  }, [activeMapping]);

  // Mutation for patching mapping (accept, reject, edit)
  const patchMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: any }) => patchMapping(id, payload),
    onSuccess: (data, variables) => {
      queryClient.setQueryData(['mappings', activeDocId], (old: Mapping[] | undefined) => {
        if (!old) return [];
        return old.map(m => m.id === variables.id ? data.mapping : m);
      });

      const previousStatus = mappings?.find(m => m.id === variables.id)?.status;
      pushUndo({
        label: `Updated mapping "${data.mapping.target_field}"`,
        undo: () => {
          if (previousStatus) {
            patchMapping(variables.id, { action: previousStatus === 'approved' ? 'accept' : previousStatus === 'rejected' ? 'reject' : 'edit' });
            refetch();
          }
        },
      });

      if (data.learned) {
        addToast({
          type: 'success',
          title: 'Learning Recorded',
          message: data.learned_message || 'Model adapted rule for future document extractions.',
        });
      }
    },
  });

  const handleAccept = useCallback((mapping: Mapping) => {
    patchMutation.mutate({
      id: mapping.id,
      payload: { action: 'accept' },
    });
  }, [patchMutation]);

  const handleReject = useCallback((mapping: Mapping) => {
    patchMutation.mutate({
      id: mapping.id,
      payload: { action: 'reject' },
    });
  }, [patchMutation]);

  const handleSaveEdit = (mapping: Mapping) => {
    patchMutation.mutate({
      id: mapping.id,
      payload: { action: 'edit', value: editValue, unit: editUnit },
    });
    setEditingMappingId(null);
  };

  const handleBulkAccept = async () => {
    try {
      const res = await bulkAcceptMappings({
        document_id: activeDocId,
        min_confidence: 0.90,
      });
      refetch();
      addToast({
        type: 'success',
        title: 'Bulk Approval Complete',
        message: `${res.accepted_count} high-confidence fields were auto-approved.`,
      });
    } catch (err: any) {
      addToast({ type: 'error', title: 'Bulk Accept Failed', message: err.message });
    }
  };

  // Keyboard navigation & shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept when typing in inputs
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement).tagName)) return;

      if (!activeMapping) return;

      if (e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        handleAccept(activeMapping);
      } else if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        handleReject(activeMapping);
      } else if (e.key === 'e' || e.key === 'E') {
        e.preventDefault();
        setEditingMappingId(activeMapping.id);
        setEditValue(activeMapping.value);
        setEditUnit(activeMapping.unit ?? '');
      } else if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault();
        const curIdx = (mappings ?? []).findIndex(m => m.id === selectedMappingId);
        if (curIdx < (mappings?.length ?? 0) - 1) {
          setSelectedMappingId(mappings![curIdx + 1].id);
        }
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault();
        const curIdx = (mappings ?? []).findIndex(m => m.id === selectedMappingId);
        if (curIdx > 0) {
          setSelectedMappingId(mappings![curIdx - 1].id);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeMapping, mappings, selectedMappingId, handleAccept, handleReject]);

  const filteredMappings = (mappings ?? []).filter(m => {
    if (filterStatus === 'all') return true;
    return m.status === filterStatus;
  });

  const totalCount = mappings?.length ?? 0;
  const approvedCount = mappings?.filter(m => m.status === 'auto' || m.status === 'approved').length ?? 0;
  const reviewCount = mappings?.filter(m => m.status === 'review').length ?? 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: 'calc(100vh - 100px)' }}>
      {/* Top Document Bar */}
      <div className="card" style={{ padding: '10px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--color-text-muted)' }}>Document:</span>
          <div style={{ display: 'flex', gap: 6 }}>
            {[
              { id: 'doc-001', name: 'rates_q3.xlsx', type: 'Excel' },
              { id: 'doc-002', name: 'filing.pdf', type: 'PDF' },
              { id: 'doc-003', name: 'notes.html', type: 'HTML' },
            ].map(doc => (
              <button
                key={doc.id}
                className={`btn btn-sm ${activeDocId === doc.id ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => {
                  setActiveDocId(doc.id);
                  setSelectedMappingId(null);
                }}
                style={{ fontSize: '0.8125rem' }}
              >
                <FileText size={13} /> {doc.name}
              </button>
            ))}
          </div>
        </div>

        {/* Bulk Action & Progress */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8125rem' }}>
            <span style={{ color: 'var(--color-text-secondary)' }}>Approved:</span>
            <strong style={{ color: 'var(--color-success)' }}>{approvedCount}/{totalCount}</strong>
            <span style={{ color: 'var(--color-text-muted)' }}>•</span>
            <span style={{ color: 'var(--color-warning)' }}>{reviewCount} need review</span>
          </div>

          <button
            id="bulk-accept-btn"
            className="btn btn-secondary btn-sm"
            onClick={handleBulkAccept}
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8125rem' }}
          >
            <Sparkles size={14} color="var(--color-accent)" />
            Bulk Accept (&gt; 90% Conf.)
          </button>
        </div>
      </div>

      {/* Split-Screen Review Body */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.05fr 1fr', gap: 16, flex: 1, minHeight: 0 }}>
        {/* Left Side: Interactive Source Document Viewer */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>Source Provenance Viewer</span>
              <span className="badge badge-auto" style={{ fontSize: '0.7rem' }}>
                {activeDocId === 'doc-001' ? 'Spreadsheet (Sheet 1)' : 'Scanned PDF'}
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                <button
                  className="btn btn-icon btn-ghost btn-sm"
                  onClick={() => setDocPage(p => Math.max(1, p - 1))}
                  disabled={docPage <= 1}
                >
                  <ChevronLeft size={14} />
                </button>
                <span>Page {docPage} of 4</span>
                <button
                  className="btn btn-icon btn-ghost btn-sm"
                  onClick={() => setDocPage(p => Math.min(4, p + 1))}
                  disabled={docPage >= 4}
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </div>

          <div
            style={{
              flex: 1,
              background: 'var(--color-surface-2)',
              overflow: 'auto',
              padding: 20,
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'flex-start',
            }}
          >
            {/* Mock Page Preview Canvas with Bounding Box Highlights */}
            <div
              style={{
                width: '100%',
                maxWidth: 540,
                background: '#ffffff',
                color: '#1e293b',
                boxShadow: 'var(--shadow-md)',
                borderRadius: 4,
                padding: '32px 36px',
                fontFamily: 'serif',
                position: 'relative',
                lineHeight: 1.6,
                fontSize: '0.85rem',
                minHeight: 520,
              }}
            >
              {/* Document Header */}
              <div style={{ borderBottom: '2px solid #334155', paddingBottom: 12, marginBottom: 20 }}>
                <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: '#64748b', letterSpacing: '0.05em' }}>
                  Vale Global Operations • Quarterly Disclosure Filing
                </div>
                <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#0f172a', marginTop: 4 }}>
                  Section 4.2: North Atlantic Mineral Extraction Summary
                </div>
                <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                  Reporting Period: Q3 Ending September 30, 2026 • Auditor Verified
                </div>
              </div>

              {/* Document Paragraph */}
              <p style={{ marginBottom: 16, color: '#334155' }}>
                Operational performance across Atlantic properties demonstrated consistent output. At the{' '}
                <mark
                  style={{
                    background: activeMapping?.target_field === 'site_name' ? 'rgba(79, 70, 229, 0.25)' : 'transparent',
                    border: activeMapping?.target_field === 'site_name' ? '2px solid #4f46e5' : 'none',
                    borderRadius: 3,
                    padding: '2px 4px',
                    fontWeight: 600,
                  }}
                >
                  Voisey's Bay
                </mark>{' '}
                processing complex, extraction rates met quarterly benchmark metrics despite seasonal maintenance.
              </p>

              {/* Document Table Mock */}
              <table style={{ width: '100%', borderCollapse: 'collapse', margin: '20px 0', fontSize: '0.8rem' }}>
                <thead>
                  <tr style={{ background: '#f8fafc', borderBottom: '2px solid #cbd5e1' }}>
                    <th style={{ textAlign: 'left', padding: '8px 10px' }}>Metric Description</th>
                    <th style={{ textAlign: 'right', padding: '8px 10px' }}>Reported Figure</th>
                    <th style={{ textAlign: 'right', padding: '8px 10px' }}>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    style={{
                      borderBottom: '1px solid #e2e8f0',
                      background: activeMapping?.target_field === 'production_t' ? 'rgba(79, 70, 229, 0.15)' : 'transparent',
                      outline: activeMapping?.target_field === 'production_t' ? '2px solid #4f46e5' : 'none',
                    }}
                  >
                    <td style={{ padding: '8px 10px', fontWeight: 600 }}>Nickel production</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 700, color: '#4f46e5' }}>
                      12,500
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', color: '#64748b' }}>lb</td>
                  </tr>

                  <tr
                    style={{
                      borderBottom: '1px solid #e2e8f0',
                      background: activeMapping?.target_field === 'unit_cost' ? 'rgba(217, 119, 6, 0.15)' : 'transparent',
                      outline: activeMapping?.target_field === 'unit_cost' ? '2px solid #d97706' : 'none',
                    }}
                  >
                    <td style={{ padding: '8px 10px', fontWeight: 600 }}>
                      Cash cost <sup style={{ color: '#d97706' }}>[1]</sup>
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 700, color: '#d97706' }}>
                      $4.2
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', color: '#64748b' }}>$/lb</td>
                  </tr>

                  <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                    <td style={{ padding: '8px 10px' }}>Copper byproduct yield</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>3,410</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', color: '#64748b' }}>lb</td>
                  </tr>
                </tbody>
              </table>

              {/* Footnote with conflict annotation */}
              <div
                style={{
                  marginTop: 24,
                  padding: '8px 12px',
                  background: activeMapping?.target_field === 'unit_cost' ? '#fffbeb' : '#f8fafc',
                  borderLeft: `3px solid ${activeMapping?.target_field === 'unit_cost' ? '#d97706' : '#94a3b8'}`,
                  fontSize: '0.75rem',
                  color: '#475569',
                }}
              >
                <strong>[1] Footnote on Cash Cost:</strong> Figures reflect direct site operational cost only and exclude provincial smelting royalties, transport tariffs, and general administrative overheads.
              </div>

              {/* Spatial Bounding Box Pin Overlay */}
              {activeMapping && (
                <div
                  style={{
                    position: 'absolute',
                    top: 12,
                    right: 12,
                    background: '#1e293b',
                    color: '#ffffff',
                    fontSize: '0.7rem',
                    padding: '4px 8px',
                    borderRadius: 4,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#4f46e5' }} />
                  Pinned: {activeMapping.target_field} ({activeMapping.source_location.type})
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Side: Field Mappings List & Detailed Actions */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Filter Tabs */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid var(--color-border)' }}>
            <div style={{ display: 'flex', gap: 6 }}>
              {['all', 'review', 'auto', 'missing'].map(st => (
                <button
                  key={st}
                  className={`btn btn-sm ${filterStatus === st ? 'btn-secondary' : 'btn-ghost'}`}
                  onClick={() => setFilterStatus(st)}
                  style={{ fontSize: '0.75rem', textTransform: 'capitalize' }}
                >
                  {st}
                </button>
              ))}
            </div>

            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
              {filteredMappings.length} field{filteredMappings.length !== 1 ? 's' : ''}
            </span>
          </div>

          {/* Mappings List */}
          <div style={{ flex: 1, overflowY: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
            {isLoading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Skeleton h={80} />
                <Skeleton h={80} />
                <Skeleton h={80} />
              </div>
            ) : filteredMappings.length === 0 ? (
              <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--color-text-muted)' }}>
                No mappings matching filter.
              </div>
            ) : (
              filteredMappings.map(mapping => {
                const isSelected = selectedMappingId === mapping.id;
                const isEditing = editingMappingId === mapping.id;

                return (
                  <div
                    key={mapping.id}
                    className="mapping-row"
                    onClick={() => setSelectedMappingId(mapping.id)}
                    style={{
                      padding: 14,
                      borderRadius: 10,
                      border: `2px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
                      background: isSelected ? 'var(--color-accent-light)' : 'var(--color-surface)',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                      boxShadow: isSelected ? 'var(--shadow-sm)' : 'none',
                    }}
                  >
                    {/* Top Row: Target Field + Status Badge + Confidence */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--color-text-primary)' }}>
                          {mapping.target_field}
                        </span>
                        <StatusBadge status={mapping.status} />
                      </div>

                      <div style={{ width: 110 }}>
                        <ConfidenceBar confidence={mapping.confidence} />
                      </div>
                    </div>

                    {/* Middle: Source Label -> Normalized Value */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', gap: 8, margin: '8px 0', fontSize: '0.85rem' }}>
                      <div style={{ background: 'var(--color-surface-2)', padding: '6px 10px', borderRadius: 6 }}>
                        <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', display: 'block' }}>Extracted Source</span>
                        <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                          {mapping.source_label || '(None)'}:{' '}
                        </span>
                        <span style={{ color: 'var(--color-text-secondary)' }}>
                          {mapping.raw_value ? `${mapping.raw_value} ${mapping.raw_unit ?? ''}` : '—'}
                        </span>
                      </div>

                      <ArrowRight size={14} color="var(--color-text-muted)" />

                      <div style={{ background: 'var(--color-surface-2)', padding: '6px 10px', borderRadius: 6 }}>
                        <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', display: 'block' }}>Canonical Schema</span>
                        {isEditing ? (
                          <div style={{ display: 'flex', gap: 4, marginTop: 2 }}>
                            <input
                              type="text"
                              value={editValue}
                              onChange={e => setEditValue(e.target.value)}
                              style={{ width: 70, padding: '2px 4px', fontSize: '0.8rem', borderRadius: 4, border: '1px solid var(--color-accent)' }}
                              autoFocus
                            />
                            <input
                              type="text"
                              value={editUnit}
                              onChange={e => setEditUnit(e.target.value)}
                              style={{ width: 45, padding: '2px 4px', fontSize: '0.8rem', borderRadius: 4, border: '1px solid var(--color-accent)' }}
                            />
                          </div>
                        ) : (
                          <span style={{ fontWeight: 700, color: 'var(--color-accent)' }}>
                            {mapping.value ? `${mapping.value} ${mapping.unit ?? ''}` : <span style={{ color: 'var(--color-error)' }}>Missing</span>}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Unit Conversion Chip if present */}
                    {mapping.conversion && (
                      <div style={{ fontSize: '0.75rem', background: 'var(--color-surface-2)', padding: '4px 8px', borderRadius: 6, color: 'var(--color-text-secondary)', marginBottom: 8, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        <Sparkles size={12} color="var(--color-accent)" />
                        <span>Formula: {mapping.conversion.formula_text}</span>
                      </div>
                    )}

                    {/* Flag Reason if needs review */}
                    {mapping.reason && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color: 'var(--color-warning)', background: 'var(--color-warning-bg)', padding: '6px 10px', borderRadius: 6, marginBottom: 8 }}>
                        <AlertTriangle size={13} style={{ flexShrink: 0 }} />
                        <span>{mapping.reason}</span>
                      </div>
                    )}

                    {/* Action Buttons */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }} onClick={e => e.stopPropagation()}>
                      {isEditing ? (
                        <>
                          <button
                            className="btn btn-sm btn-ghost"
                            onClick={() => setEditingMappingId(null)}
                          >
                            Cancel
                          </button>
                          <button
                            className="btn btn-sm btn-primary"
                            onClick={() => handleSaveEdit(mapping)}
                          >
                            Save Correction
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="btn btn-sm btn-ghost"
                            onClick={() => {
                              setEditingMappingId(mapping.id);
                              setEditValue(mapping.value);
                              setEditUnit(mapping.unit ?? '');
                            }}
                            title="Edit value or unit manually (E)"
                          >
                            <Edit3 size={13} /> Edit
                          </button>
                          <button
                            className="btn btn-sm btn-danger"
                            onClick={() => handleReject(mapping)}
                            title="Reject mapping (R)"
                          >
                            <X size={13} /> Reject
                          </button>
                          <button
                            className="btn btn-sm btn-primary"
                            onClick={() => handleAccept(mapping)}
                            title="Accept mapping (A)"
                          >
                            <Check size={13} /> Accept
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Keyboard Shortcuts Footer Hint */}
          <div style={{ padding: '8px 16px', background: 'var(--color-surface-2)', borderTop: '1px solid var(--color-border)', fontSize: '0.75rem', color: 'var(--color-text-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: 12 }}>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '2px 5px', borderRadius: 4, border: '1px solid var(--color-border)', fontWeight: 600 }}>A</kbd> Accept</span>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '2px 5px', borderRadius: 4, border: '1px solid var(--color-border)', fontWeight: 600 }}>R</kbd> Reject</span>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '2px 5px', borderRadius: 4, border: '1px solid var(--color-border)', fontWeight: 600 }}>E</kbd> Edit</span>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '2px 5px', borderRadius: 4, border: '1px solid var(--color-border)', fontWeight: 600 }}>↓ / ↑</kbd> Next</span>
            </div>
            <span>Auto-learning enabled</span>
          </div>
        </div>
      </div>
    </div>
  );
}
