import React, { useEffect, useRef } from 'react';
import { AlertTriangle, X } from 'lucide-react';

export interface CancelConfirmModalProps {
  isOpen: boolean;
  onConfirm: () => void;
  onClose: () => void;
  isLoading?: boolean;
}

export function CancelConfirmModal({
  isOpen,
  onConfirm,
  onClose,
  isLoading = false,
}: CancelConfirmModalProps) {
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isOpen) {
      confirmBtnRef.current?.focus();
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          onClose();
        }
      };
      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="cancel-dialog-title"
      aria-describedby="cancel-dialog-desc"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.55)',
        backdropFilter: 'blur(2px)',
        padding: 16,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="card"
        style={{
          width: '100%',
          maxWidth: 440,
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 12,
          boxShadow: 'var(--shadow-xl)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            padding: '16px 20px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            borderBottom: '1px solid var(--color-border-subtle)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                background: 'var(--color-warning-bg)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-warning)',
              }}
              aria-hidden="true"
            >
              <AlertTriangle size={18} />
            </div>
            <h3
              id="cancel-dialog-title"
              style={{ margin: 0, fontSize: '1rem', fontWeight: 600, color: 'var(--color-text-primary)' }}
            >
              Cancel Pipeline Run
            </h3>
          </div>

          <button
            className="btn btn-ghost btn-sm btn-icon"
            onClick={onClose}
            aria-label="Close dialog"
            style={{ minHeight: 44, minWidth: 44 }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: '20px' }}>
          <p
            id="cancel-dialog-desc"
            style={{ margin: 0, fontSize: '0.9rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}
          >
            Stop processing? Results extracted so far are kept in the current batch.
          </p>
        </div>

        <div
          style={{
            padding: '14px 20px',
            background: 'var(--color-surface-2)',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 10,
            borderTop: '1px solid var(--color-border-subtle)',
          }}
        >
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            disabled={isLoading}
            style={{ minHeight: 44 }}
          >
            Continue Processing
          </button>
          <button
            ref={confirmBtnRef}
            type="button"
            className="btn btn-danger"
            onClick={onConfirm}
            disabled={isLoading}
            style={{ minHeight: 44 }}
          >
            {isLoading ? 'Stopping…' : 'Stop Processing'}
          </button>
        </div>
      </div>
    </div>
  );
}
