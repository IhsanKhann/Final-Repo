import React, { useState, useCallback } from 'react';
import type { Toast } from '../../context/AppContext';
import { useToast, useUndo } from '../../context/AppContext';
import { CheckCircle2, AlertCircle, XCircle, Info, X, RotateCcw } from 'lucide-react';

// ─── Toast Container ──────────────────────────────────────────────────────────
const TOAST_ICONS: Record<Toast['type'], React.ReactNode> = {
  success: <CheckCircle2 size={16} color="var(--color-success)" />,
  error: <XCircle size={16} color="var(--color-error)" />,
  warning: <AlertCircle size={16} color="var(--color-warning)" />,
  info: <Info size={16} color="var(--color-info)" />,
};

export function ToastContainer() {
  const { toasts, removeToast } = useToast();
  if (toasts.length === 0) return null;
  return (
    <div className="toast-container" aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} className="toast" role="alert">
          {TOAST_ICONS[t.type]}
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>{t.title}</div>
            {t.message && <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>{t.message}</div>}
          </div>
          {t.action && (
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => { t.action!.onClick(); removeToast(t.id); }}
            >{t.action.label}</button>
          )}
          <button
            className="btn btn-icon btn-ghost btn-sm"
            onClick={() => removeToast(t.id)}
            aria-label="Dismiss notification"
          ><X size={14} /></button>
        </div>
      ))}
    </div>
  );
}

// ─── Undo Bar ─────────────────────────────────────────────────────────────────
export function UndoBar() {
  const { undoEntry, clearUndo } = useUndo();
  if (!undoEntry) return null;
  return (
    <div className="undo-bar" role="status" aria-live="polite">
      <span style={{ fontSize: '0.875rem' }}>{undoEntry.label}</span>
      <button
        className="btn btn-sm"
        style={{ background: 'var(--color-accent)', color: 'white', border: 'none' }}
        onClick={() => { undoEntry.undo(); clearUndo(); }}
      >
        <RotateCcw size={13} /> Undo
      </button>
      <button
        className="btn btn-icon btn-sm"
        style={{ background: 'transparent', color: 'var(--color-bg)', border: 'none', opacity: 0.7 }}
        onClick={clearUndo}
        aria-label="Dismiss undo"
      ><X size={14} /></button>
    </div>
  );
}
