import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Check, X, Edit3, ChevronRight, ChevronLeft, AlertTriangle,
  CheckCircle2, FileText, ArrowRight, Sparkles, Filter,
  Maximize2, ZoomIn, ZoomOut, RotateCcw, Info, Sliders,
  HelpCircle, Eye, Download, ShieldCheck, FileSpreadsheet,
  AlertCircle
} from 'lucide-react';
import { getDocumentMappings, patchMapping, bulkAcceptMappings } from '../api/client';
import type { Mapping, MappingStatus } from '../api/types';
import { ConfidenceBar, StatusBadge, Skeleton } from '../components/ui/SharedUi';
import { useToast, useUndo } from '../context/AppContext';

export function ReviewPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const { pushUndo, undoEntry } = useUndo();

  const [activeDocId, setActiveDocId] = useState('doc-001');
  const [activeDocIndex, setActiveDocIndex] = useState(0);
  const [selectedMappingId, setSelectedMappingId] = useState<string | null>('m2');
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [zoomLevel, setZoomLevel] = useState(100);
  const [docPage, setDocPage] = useState(3);
  const [lastSavedTime, setLastSavedTime] = useState<string>('Saved just now');

  // Form states inside the Record Detail Drawer
  const [drawerValue, setDrawerValue] = useState('');
  const [drawerUnit, setDrawerUnit] = useState('');
  const [drawerReason, setDrawerReason] = useState('');
  const [showExportWarning, setShowExportWarning] = useState(false);

  const documentsList = useMemo(() => [
    { id: 'doc-001', name: 'rates_q3.xlsx', type: 'sheet' as const, sheet: 'Q3_Rates' },
    { id: 'doc-002', name: 'filing.pdf', type: 'pdf' as const, pages: 4 },
    { id: 'doc-003', name: 'notes.html', type: 'text' as const },
  ], []);

  const currentDoc = documentsList[activeDocIndex] || documentsList[0];

  const { data: mappings, isLoading, refetch } = useQuery({
    queryKey: ['mappings', activeDocId],
    queryFn: () => getDocumentMappings(activeDocId),
  });

  const activeMapping = useMemo(() => {
    return (mappings ?? []).find(m => m.id === selectedMappingId) ?? mappings?.[0];
  }, [mappings, selectedMappingId]);

  // Set initial selected mapping and open drawer when loaded
  useEffect(() => {
    if (mappings && mappings.length > 0) {
      if (!selectedMappingId || !mappings.some(m => m.id === selectedMappingId)) {
        const firstNeedsReview = mappings.find(m => m.status === 'review' || m.status === 'missing');
        setSelectedMappingId(firstNeedsReview ? firstNeedsReview.id : mappings[0].id);
      }
      setDrawerOpen(true);
    }
  }, [mappings, selectedMappingId]);

  // Sync drawer form state when active mapping changes
  useEffect(() => {
    if (activeMapping) {
      setDrawerValue(activeMapping.value);
      setDrawerUnit(activeMapping.unit ?? '');
      setDrawerReason(activeMapping.reason ?? '');
      if (activeMapping.source_location?.type === 'pdf') {
        setDocPage(activeMapping.source_location.page);
      }
    }
  }, [activeMapping]);

  // Mutation for patching mapping (accept, reject, edit)
  const patchMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: any }) => patchMapping(id, payload),
    onSuccess: (data, variables) => {
      setLastSavedTime(`Saved at ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`);
      queryClient.setQueryData(['mappings', activeDocId], (old: Mapping[] | undefined) => {
        if (!old) return [];
        return old.map(m => m.id === variables.id ? data.mapping : m);
      });

      const previous = mappings?.find(m => m.id === variables.id);
      pushUndo({
        label: `Updated "${data.mapping.target_field}"`,
        undo: () => {
          if (previous) {
            patchMapping(variables.id, {
              action: previous.status === 'approved' ? 'accept' : previous.status === 'rejected' ? 'reject' : 'edit',
              value: previous.value,
              unit: previous.unit,
            });
            refetch();
          }
        },
      });

      if (data.learned) {
        addToast({
          type: 'success',
          title: 'Learned New Mapping Rule',
          message: data.learned_message || `Learned: "${data.mapping.source_label}" → "${data.mapping.target_field}"`,
          duration: 6000,
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

  const handleSaveDrawer = () => {
    if (!activeMapping) return;
    patchMutation.mutate({
      id: activeMapping.id,
      payload: {
        action: 'edit',
        value: drawerValue,
        unit: drawerUnit || undefined,
        reason: drawerReason || undefined,
      },
    });
    setDrawerOpen(false);
  };

  const handleRestoreOriginal = () => {
    if (!activeMapping) return;
    setDrawerValue(activeMapping.raw_value);
    setDrawerUnit(activeMapping.raw_unit ?? '');
    setDrawerReason('');
    addToast({
      type: 'info',
      title: 'Restored Raw Source Value',
      message: `Reset value to "${activeMapping.raw_value} ${activeMapping.raw_unit ?? ''}" from original document extraction.`,
    });
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
        title: 'High-Confidence Fields Accepted',
        message: `${res.accepted_count} fields (≥ 90% confidence) were approved automatically.`,
      });
    } catch (err: any) {
      addToast({ type: 'error', title: 'Bulk Accept Failed', message: err.message });
    }
  };

  // Keyboard navigation: J/K move, A accept, E edit, R reject, Z undo, / search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept when user is typing in form controls
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement).tagName)) return;

      if (e.key === '/') {
        e.preventDefault();
        document.getElementById('header-search')?.focus();
        return;
      }

      if (e.key === 'z' || e.key === 'Z') {
        if (undoEntry) {
          e.preventDefault();
          undoEntry.undo();
          addToast({ type: 'info', title: 'Action Undone', message: undoEntry.label });
        }
        return;
      }

      if (!activeMapping) return;

      if (e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        handleAccept(activeMapping);
      } else if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        handleReject(activeMapping);
      } else if (e.key === 'e' || e.key === 'E') {
        e.preventDefault();
        setDrawerOpen(true);
      } else if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault();
        const curIdx = (mappings ?? []).findIndex(m => m.id === selectedMappingId);
        if (curIdx < (mappings?.length ?? 0) - 1) {
          setSelectedMappingId(mappings![curIdx + 1].id);
        }
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault();
        const curIdx = (mappings ?? []).findIndex(m => m.id === selectedMappingId);
        if (curIdx > 0) {
          setSelectedMappingId(mappings![curIdx - 1].id);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeMapping, mappings, selectedMappingId, handleAccept, handleReject, undoEntry, addToast]);

  // Sort mappings so Needs Review and Missing are surfaced first!
  const sortedMappings = useMemo(() => {
    if (!mappings) return [];
    return [...mappings].sort((a, b) => {
      const priorityOrder: Record<MappingStatus, number> = {
        review: 0,
        missing: 1,
        auto: 2,
        approved: 3,
        rejected: 4,
      };
      return priorityOrder[a.status] - priorityOrder[b.status];
    });
  }, [mappings]);

  const filteredMappings = sortedMappings.filter(m => {
    if (filterStatus === 'all') return true;
    return m.status === filterStatus;
  });

  const totalCount = mappings?.length ?? 0;
  const approvedCount = mappings?.filter(m => m.status === 'auto' || m.status === 'approved').length ?? 0;
  const unresolvedReviewCount = mappings?.filter(m => m.status === 'review' || m.status === 'missing').length ?? 0;

  const handleNextDoc = () => {
    if (activeDocIndex < documentsList.length - 1) {
      const nextIdx = activeDocIndex + 1;
      setActiveDocIndex(nextIdx);
      setActiveDocId(documentsList[nextIdx].id);
      setSelectedMappingId(null);
    }
  };

  const handlePrevDoc = () => {
    if (activeDocIndex > 0) {
      const prevIdx = activeDocIndex - 1;
      setActiveDocIndex(prevIdx);
      setActiveDocId(documentsList[prevIdx].id);
      setSelectedMappingId(null);
    }
  };

  const handleExportClick = () => {
    if (unresolvedReviewCount > 0) {
      setShowExportWarning(true);
    } else {
      navigate('/dataset');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, height: 'calc(100vh - 84px)' }}>
      {/* Breadcrumb, Document Navigator, and Status Ribbon */}
      <div className="card" style={{ padding: '8px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* Document Prev/Next */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <button
              className="btn btn-sm btn-ghost btn-icon"
              onClick={handlePrevDoc}
              disabled={activeDocIndex === 0}
              aria-label="Previous document"
            >
              <ChevronLeft size={16} />
            </button>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
              Document {activeDocIndex + 1} of {documentsList.length}
            </span>
            <button
              className="btn btn-sm btn-ghost btn-icon"
              onClick={handleNextDoc}
              disabled={activeDocIndex === documentsList.length - 1}
              aria-label="Next document"
            >
              <ChevronRight size={16} />
            </button>
          </div>

          <div style={{ width: 1, height: 18, background: 'var(--color-border)' }} />

          {/* Document switcher pills */}
          <div style={{ display: 'flex', gap: 6 }}>
            {documentsList.map((doc, idx) => (
              <button
                key={doc.id}
                className={`btn btn-sm ${activeDocId === doc.id ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => {
                  setActiveDocIndex(idx);
                  setActiveDocId(doc.id);
                  setSelectedMappingId(null);
                }}
                style={{ fontSize: '0.8125rem', padding: '4px 10px' }}
              >
                {doc.type === 'sheet' ? <FileSpreadsheet size={13} /> : <FileText size={13} />}
                {doc.name}
              </button>
            ))}
          </div>
        </div>

        {/* Review Counts & Export Button */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8125rem' }}>
            <span style={{ color: 'var(--color-text-muted)' }}>{lastSavedTime}</span>
            <span style={{ color: 'var(--color-border)' }}>|</span>
            {unresolvedReviewCount > 0 ? (
              <span className="badge badge-review" style={{ fontSize: '0.75rem' }}>
                <AlertTriangle size={12} /> {unresolvedReviewCount} field{unresolvedReviewCount !== 1 ? 's' : ''} need review
              </span>
            ) : (
              <span className="badge badge-auto" style={{ fontSize: '0.75rem' }}>
                <CheckCircle2 size={12} /> All fields resolved
              </span>
            )}
          </div>

          <button
            id="review-export-btn"
            className="btn btn-secondary btn-sm"
            onClick={handleExportClick}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Download size={14} /> Export Dataset
          </button>
        </div>
      </div>

      {/* Rossum-style Split View Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: drawerOpen ? '1fr 1fr 340px' : '1.1fr 1fr', gap: 14, flex: 1, minHeight: 0, transition: 'all 0.25s ease' }}>
        {/* LEFT COLUMN: Source Document Provenance Viewer */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>Source Document</span>
              <span className="badge badge-auto" style={{ fontSize: '0.7rem' }}>
                {currentDoc.type === 'sheet' ? 'Excel Table Preview' : 'Interactive Document View'}
              </span>
            </div>

            {/* Viewer controls: Zoom & Page navigation */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <button
                  className="btn btn-icon btn-ghost btn-sm"
                  onClick={() => setZoomLevel(z => Math.max(70, z - 10))}
                  title="Zoom Out"
                >
                  <ZoomOut size={13} />
                </button>
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', minWidth: 36, textAlign: 'center' }}>
                  {zoomLevel}%
                </span>
                <button
                  className="btn btn-icon btn-ghost btn-sm"
                  onClick={() => setZoomLevel(z => Math.min(150, z + 10))}
                  title="Zoom In"
                >
                  <ZoomIn size={13} />
                </button>
              </div>

              {currentDoc.type === 'pdf' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.75rem', color: 'var(--color-text-muted)', borderLeft: '1px solid var(--color-border)', paddingLeft: 8 }}>
                  <button
                    className="btn btn-icon btn-ghost btn-sm"
                    onClick={() => setDocPage(p => Math.max(1, p - 1))}
                    disabled={docPage <= 1}
                  >
                    <ChevronLeft size={13} />
                  </button>
                  <span>Page {docPage} of {currentDoc.pages ?? 4}</span>
                  <button
                    className="btn btn-icon btn-ghost btn-sm"
                    onClick={() => setDocPage(p => Math.min(currentDoc.pages ?? 4, p + 1))}
                    disabled={docPage >= (currentDoc.pages ?? 4)}
                  >
                    <ChevronRight size={13} />
                  </button>
                </div>
              )}
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
            {/* Transform container for zoom */}
            <div style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center', transition: 'transform 0.15s ease', width: '100%', maxWidth: 540 }}>
              {currentDoc.type === 'sheet' ? (
                /* Excel / Spreadsheet preview mode with cell highlights */
                <div
                  className="source-paper-canvas"
                  style={{
                    background: '#ffffff',
                    border: '1px solid #cbd5e1',
                    borderRadius: 6,
                    boxShadow: 'var(--shadow)',
                    overflow: 'hidden',
                    fontFamily: 'system-ui, -apple-system, sans-serif',
                    fontSize: '0.8rem',
                  }}
                >
                  <div style={{ background: '#f1f5f9', padding: '6px 12px', borderBottom: '1px solid #cbd5e1', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, color: '#475569' }}>Sheet: {currentDoc.sheet}</span>
                    <span style={{ fontSize: '0.7rem', color: '#64748b' }}>Active Cell: {activeMapping?.target_field === 'production_t' ? 'B12' : activeMapping?.target_field === 'unit_cost' ? 'B13' : 'A4'}</span>
                  </div>

                  <table style={{ width: '100%', borderCollapse: 'collapse', color: '#1e293b' }}>
                    <thead>
                      <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0', color: '#64748b', fontSize: '0.75rem' }}>
                        <th style={{ width: 36, padding: '6px 8px', textAlign: 'center', background: '#f1f5f9', borderRight: '1px solid #e2e8f0' }}>#</th>
                        <th style={{ textAlign: 'left', padding: '6px 10px', borderRight: '1px solid #e2e8f0' }}>A: Indicator / Property</th>
                        <th style={{ textAlign: 'right', padding: '6px 10px', borderRight: '1px solid #e2e8f0' }}>B: Reported Value</th>
                        <th style={{ textAlign: 'left', padding: '6px 10px' }}>C: Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                        <td style={{ textAlign: 'center', background: '#f8fafc', borderRight: '1px solid #e2e8f0', color: '#94a3b8' }}>10</td>
                        <td style={{ padding: '6px 10px', borderRight: '1px solid #e2e8f0', fontWeight: 600 }}>Mine Operation Name</td>
                        <td
                          style={{
                            textAlign: 'right', padding: '6px 10px', borderRight: '1px solid #e2e8f0',
                            background: activeMapping?.target_field === 'site_name' ? 'rgba(79, 70, 229, 0.2)' : 'transparent',
                            outline: activeMapping?.target_field === 'site_name' ? '2px solid #4f46e5' : 'none',
                            fontWeight: activeMapping?.target_field === 'site_name' ? 700 : 400,
                          }}
                        >
                          Voisey's Bay
                        </td>
                        <td style={{ padding: '6px 10px', color: '#64748b' }}>Primary asset</td>
                      </tr>

                      <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                        <td style={{ textAlign: 'center', background: '#f8fafc', borderRight: '1px solid #e2e8f0', color: '#94a3b8' }}>11</td>
                        <td style={{ padding: '6px 10px', borderRight: '1px solid #e2e8f0' }}>Period End Date</td>
                        <td style={{ textAlign: 'right', padding: '6px 10px', borderRight: '1px solid #e2e8f0' }}>30-Sep-2026</td>
                        <td style={{ padding: '6px 10px', color: '#64748b' }}>Quarterly close</td>
                      </tr>

                      <tr
                        style={{
                          borderBottom: '1px solid #e2e8f0',
                          background: activeMapping?.target_field === 'production_t' ? 'rgba(79, 70, 229, 0.12)' : 'transparent',
                        }}
                      >
                        <td style={{ textAlign: 'center', background: '#f8fafc', borderRight: '1px solid #e2e8f0', color: '#94a3b8' }}>12</td>
                        <td style={{ padding: '6px 10px', borderRight: '1px solid #e2e8f0', fontWeight: 600 }}>
                          Nickel production
                        </td>
                        <td
                          style={{
                            textAlign: 'right', padding: '6px 10px', borderRight: '1px solid #e2e8f0',
                            background: activeMapping?.target_field === 'production_t' ? 'rgba(79, 70, 229, 0.25)' : 'transparent',
                            outline: activeMapping?.target_field === 'production_t' ? '2px solid #4f46e5' : 'none',
                            fontWeight: 700, color: '#4f46e5',
                          }}
                        >
                          12,500 lb
                        </td>
                        <td style={{ padding: '6px 10px', color: '#64748b' }}>Refined cathode</td>
                      </tr>

                      <tr
                        style={{
                          borderBottom: '1px solid #e2e8f0',
                          background: activeMapping?.target_field === 'unit_cost' ? 'rgba(217, 119, 6, 0.12)' : 'transparent',
                        }}
                      >
                        <td style={{ textAlign: 'center', background: '#f8fafc', borderRight: '1px solid #e2e8f0', color: '#94a3b8' }}>13</td>
                        <td style={{ padding: '6px 10px', borderRight: '1px solid #e2e8f0', fontWeight: 600 }}>
                          Cash cost *
                        </td>
                        <td
                          style={{
                            textAlign: 'right', padding: '6px 10px', borderRight: '1px solid #e2e8f0',
                            background: activeMapping?.target_field === 'unit_cost' ? 'rgba(217, 119, 6, 0.25)' : 'transparent',
                            outline: activeMapping?.target_field === 'unit_cost' ? '2px solid #d97706' : 'none',
                            fontWeight: 700, color: '#d97706',
                          }}
                        >
                          $4.2 /lb
                        </td>
                        <td style={{ padding: '6px 10px', color: '#b45309', fontSize: '0.75rem' }}>* Excl. royalties</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : (
                /* PDF / Document scan layout with spatial bounding boxes */
                <div
                  className="source-paper-canvas"
                  style={{
                    background: '#ffffff',
                    color: '#1e293b',
                    boxShadow: 'var(--shadow-md)',
                    borderRadius: 4,
                    padding: '30px 34px',
                    fontFamily: 'serif',
                    position: 'relative',
                    lineHeight: 1.6,
                    fontSize: '0.85rem',
                    minHeight: 500,
                  }}
                >
                  <div style={{ borderBottom: '2px solid #334155', paddingBottom: 10, marginBottom: 16 }}>
                    <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: '#64748b' }}>
                      Official Operational Filing • Section 4.2 Production
                    </div>
                    <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#0f172a', marginTop: 2 }}>
                      Atlantic Properties Mineral Extraction Summary
                    </div>
                  </div>

                  <p style={{ marginBottom: 14 }}>
                    Operational yields from Thompson & Voisey complexes recorded aggregate volume of{' '}
                    <mark
                      style={{
                        background: activeMapping?.target_field === 'production_t' ? 'rgba(79, 70, 229, 0.25)' : 'transparent',
                        border: activeMapping?.target_field === 'production_t' ? '2px solid #4f46e5' : 'none',
                        padding: '2px 4px',
                        borderRadius: 3,
                        fontWeight: 600,
                      }}
                    >
                      8,200 lb
                    </mark>{' '}
                    of refined concentrate.
                  </p>

                  <div
                    style={{
                      marginTop: 20,
                      padding: '10px 14px',
                      background: '#fffbeb',
                      borderLeft: '3px solid #d97706',
                      fontSize: '0.75rem',
                      color: '#475569',
                    }}
                  >
                    <strong>Footnote Annotation:</strong> Extraction figures are subject to final metallurgical balancing.
                  </div>

                  {/* Visual bounding box locator overlay */}
                  <div
                    style={{
                      position: 'absolute',
                      top: 10,
                      right: 10,
                      background: '#0f172a',
                      color: '#ffffff',
                      fontSize: '0.7rem',
                      padding: '3px 8px',
                      borderRadius: 4,
                    }}
                  >
                    BBox: [0.10, 0.22, 0.50, 0.04] (Normalized)
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* MIDDLE COLUMN: Proposed Mappings List */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Filter Bar & Bulk Accept */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', borderBottom: '1px solid var(--color-border)', flexWrap: 'wrap', gap: 8 }}>
            <div style={{ display: 'flex', gap: 4 }}>
              {['all', 'review', 'auto', 'missing'].map(st => (
                <button
                  key={st}
                  className={`btn btn-sm ${filterStatus === st ? 'btn-secondary' : 'btn-ghost'}`}
                  onClick={() => setFilterStatus(st)}
                  style={{ fontSize: '0.75rem', textTransform: 'capitalize', padding: '3px 8px' }}
                >
                  {st === 'review' ? 'Needs Review' : st}
                </button>
              ))}
            </div>

            <button
              id="bulk-accept-high-conf"
              className="btn btn-primary btn-sm"
              onClick={handleBulkAccept}
              style={{ fontSize: '0.75rem', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: 4 }}
            >
              <Sparkles size={13} />
              Accept all &ge; 90%
            </button>
          </div>

          {/* Mappings List */}
          <div style={{ flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {isLoading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <Skeleton h={80} />
                <Skeleton h={80} />
                <Skeleton h={80} />
              </div>
            ) : filteredMappings.length === 0 ? (
              <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--color-text-muted)' }}>
                No fields match current filter.
              </div>
            ) : (
              filteredMappings.map(mapping => {
                const isSelected = selectedMappingId === mapping.id;

                return (
                  <div
                    key={mapping.id}
                    className="mapping-row"
                    onClick={() => {
                      setSelectedMappingId(mapping.id);
                      setDrawerOpen(true);
                    }}
                    style={{
                      padding: 12,
                      borderRadius: 8,
                      border: `2px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
                      background: isSelected ? 'var(--color-accent-light)' : 'var(--color-surface)',
                      cursor: 'pointer',
                      transition: 'all 0.12s ease',
                      boxShadow: isSelected ? 'var(--shadow-sm)' : 'none',
                    }}
                  >
                    {/* Top Row: Target Field + Status Badge + Confidence Score */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontWeight: 700, fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>
                          {mapping.target_field}
                        </span>
                        <StatusBadge status={mapping.status} />
                      </div>

                      <div style={{ width: 100 }}>
                        <ConfidenceBar confidence={mapping.confidence} />
                      </div>
                    </div>

                    {/* Middle Row: Source Label & Raw value -> Target Canonical Value */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', gap: 8, margin: '6px 0', fontSize: '0.8125rem' }}>
                      <div style={{ background: 'var(--color-surface-2)', padding: '5px 8px', borderRadius: 4 }}>
                        <span style={{ fontSize: '0.6875rem', color: 'var(--color-text-muted)', display: 'block' }}>Extracted Source</span>
                        <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                          {mapping.source_label || '(Not in doc)'}:{' '}
                        </span>
                        <span style={{ color: 'var(--color-text-secondary)' }}>
                          {mapping.raw_value ? `${mapping.raw_value} ${mapping.raw_unit ?? ''}` : '—'}
                        </span>
                      </div>

                      <ArrowRight size={13} color="var(--color-text-muted)" />

                      <div style={{ background: 'var(--color-surface-2)', padding: '5px 8px', borderRadius: 4 }}>
                        <span style={{ fontSize: '0.6875rem', color: 'var(--color-text-muted)', display: 'block' }}>Canonical Target</span>
                        <span style={{ fontWeight: 700, color: mapping.value ? 'var(--color-accent)' : 'var(--color-error)' }}>
                          {mapping.value ? `${mapping.value} ${mapping.unit ?? ''}` : 'Missing'}
                        </span>
                      </div>
                    </div>

                    {/* Unit formula callout */}
                    {mapping.conversion && (
                      <div style={{ fontSize: '0.7rem', color: 'var(--color-text-secondary)', background: 'var(--color-surface-2)', padding: '3px 6px', borderRadius: 4, marginBottom: 6, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <Sparkles size={11} color="var(--color-accent)" />
                        <span>{mapping.conversion.formula_text}</span>
                      </div>
                    )}

                    {/* Reason callout */}
                    {mapping.reason && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color: 'var(--color-warning)', background: 'var(--color-warning-bg)', padding: '5px 8px', borderRadius: 4, marginBottom: 6 }}>
                        <AlertTriangle size={12} style={{ flexShrink: 0 }} />
                        <span>{mapping.reason}</span>
                      </div>
                    )}

                    {/* Action buttons */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 4 }} onClick={e => e.stopPropagation()}>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => {
                          setSelectedMappingId(mapping.id);
                          setDrawerOpen(true);
                        }}
                        title="Open Record Detail Drawer (E)"
                        style={{ fontSize: '0.75rem', padding: '3px 8px' }}
                      >
                        <Edit3 size={12} /> Edit
                      </button>
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => handleReject(mapping)}
                        title="Reject mapping (R)"
                        style={{ fontSize: '0.75rem', padding: '3px 8px' }}
                      >
                        <X size={12} /> Reject
                      </button>
                      <button
                        className="btn btn-sm btn-primary"
                        onClick={() => handleAccept(mapping)}
                        title="Accept mapping (A)"
                        style={{ fontSize: '0.75rem', padding: '3px 8px' }}
                      >
                        <Check size={12} /> Accept
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Keyboard Hints Bar */}
          <div style={{ padding: '6px 12px', background: 'var(--color-surface-2)', borderTop: '1px solid var(--color-border)', fontSize: '0.7rem', color: 'var(--color-text-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: 10 }}>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '1px 4px', borderRadius: 3, border: '1px solid var(--color-border)', fontWeight: 600 }}>J/K</kbd> Navigate</span>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '1px 4px', borderRadius: 3, border: '1px solid var(--color-border)', fontWeight: 600 }}>A</kbd> Accept</span>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '1px 4px', borderRadius: 3, border: '1px solid var(--color-border)', fontWeight: 600 }}>E</kbd> Detail Drawer</span>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '1px 4px', borderRadius: 3, border: '1px solid var(--color-border)', fontWeight: 600 }}>R</kbd> Reject</span>
              <span><kbd style={{ background: 'var(--color-surface)', padding: '1px 4px', borderRadius: 3, border: '1px solid var(--color-border)', fontWeight: 600 }}>Z</kbd> Undo</span>
            </div>
            <span>Auto-learning enabled</span>
          </div>
        </div>

        {/* RIGHT COLUMN: Screen 5: Record Detail Drawer */}
        {drawerOpen && activeMapping && (
          <div
            className="card"
            style={{
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              borderLeft: '2px solid var(--color-accent)',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            {/* Drawer Header */}
            <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px' }}>
              <div>
                <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>Record Detail</span>
                <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--color-text-primary)' }}>
                  {activeMapping.target_field}
                </div>
              </div>
              <button
                className="btn btn-icon btn-ghost btn-sm"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close detail drawer"
              >
                <X size={16} />
              </button>
            </div>

            {/* Drawer Body */}
            <div style={{ flex: 1, overflowY: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 14 }}>
              {/* Confidence & Plain-Language Reason */}
              <div>
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-muted)' }}>Confidence Assessment</span>
                <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <ConfidenceBar confidence={activeMapping.confidence} />
                </div>
                {activeMapping.reason && (
                  <div style={{ marginTop: 6, fontSize: '0.8rem', color: 'var(--color-warning)', background: 'var(--color-warning-bg)', padding: '6px 10px', borderRadius: 6, lineHeight: 1.4 }}>
                    <strong>Why flagged:</strong> {activeMapping.reason}
                  </div>
                )}
              </div>

              {/* Unit Conversion Breakdown */}
              {activeMapping.conversion && (
                <div style={{ background: 'var(--color-surface-2)', padding: '10px 12px', borderRadius: 6 }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-primary)', display: 'block', marginBottom: 4 }}>
                    Unit Conversion Calculation
                  </span>
                  <div style={{ fontFamily: 'monospace', fontSize: '0.8rem', color: 'var(--color-accent)', fontWeight: 600 }}>
                    {activeMapping.conversion.formula_text}
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    Rule: {activeMapping.conversion.rule_id} (Multiplier factor: {activeMapping.conversion.factor})
                  </div>
                </div>
              )}

              {/* Business Validation Results */}
              <div>
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-muted)', display: 'block', marginBottom: 6 }}>
                  Validation Assertions ({activeMapping.validations.length})
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {activeMapping.validations.map((v, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '6px 10px',
                        background: 'var(--color-surface-2)',
                        borderRadius: 4,
                        fontSize: '0.75rem',
                      }}
                    >
                      <span style={{ fontWeight: 500 }}>{v.name}</span>
                      <span className={`badge ${v.ok ? 'badge-auto' : 'badge-missing'}`} style={{ fontSize: '0.6875rem' }}>
                        {v.ok ? 'Pass' : 'Fail'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Editable Value & Unit Form */}
              <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 12 }}>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                  Canonical Output Value & Unit
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: 8 }}>
                  <input
                    type="text"
                    value={drawerValue}
                    onChange={e => setDrawerValue(e.target.value)}
                    placeholder="Value"
                    style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.85rem' }}
                  />
                  <input
                    type="text"
                    value={drawerUnit}
                    onChange={e => setDrawerUnit(e.target.value)}
                    placeholder="Unit (e.g. t)"
                    style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.85rem' }}
                  />
                </div>
              </div>

              {/* Optional Reason / Notes */}
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                  Analyst Rationale / Override Reason
                </label>
                <textarea
                  rows={2}
                  value={drawerReason}
                  onChange={e => setDrawerReason(e.target.value)}
                  placeholder="Explain why this field was adjusted…"
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.8rem', resize: 'none' }}
                />
              </div>

              {/* Drawer Actions */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 'auto', paddingTop: 10 }}>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleSaveDrawer}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
                >
                  <Check size={14} /> Approve & Save Correction
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={handleRestoreOriginal}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
                >
                  <RotateCcw size={13} /> Restore Raw Source Value
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Export Warning Modal when unreviewed fields remain */}
      {showExportWarning && (
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
          onClick={() => setShowExportWarning(false)}
        >
          <div
            className="card"
            style={{ width: '100%', maxWidth: 460, padding: 20 }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--color-warning)', marginBottom: 12 }}>
              <AlertTriangle size={24} />
              <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                Unresolved Flagged Fields
              </h3>
            </div>
            <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', lineHeight: 1.5, marginBottom: 16 }}>
              There are still <strong>{unresolvedReviewCount} fields</strong> requiring analyst review in this document. Exporting now may include unverified estimates in downstream datasets.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setShowExportWarning(false)}
              >
                Review Fields Now
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => {
                  setShowExportWarning(false);
                  navigate('/dataset');
                }}
              >
                Export Anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
