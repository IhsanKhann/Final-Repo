import type { MappingStatus } from '../../api/types';
import {
  CheckCircle2, AlertCircle, XCircle, CircleCheck, Loader2,
} from 'lucide-react';

// ─── Confidence Utilities ─────────────────────────────────────────────────────
export function confidenceLevel(c: number): 'high' | 'medium' | 'low' {
  if (c >= 0.90) return 'high';
  if (c >= 0.60) return 'medium';
  return 'low';
}

export function ConfidenceBar({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const level = confidenceLevel(confidence);
  return (
    <div className="confidence-bar-wrapper">
      <div className="confidence-bar-track" style={{ minWidth: 60 }}>
        <div
          className={`confidence-bar-fill ${level}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`confidence-pct ${level}`}>{pct}%</span>
    </div>
  );
}

// ─── Status Badge ─────────────────────────────────────────────────────────────
const STATUS_CONFIG: Record<MappingStatus, { label: string; icon: React.ReactNode; cls: string }> = {
  auto: {
    label: 'Auto-approved',
    icon: <CheckCircle2 size={12} />,
    cls: 'badge-auto',
  },
  review: {
    label: 'Needs review',
    icon: <AlertCircle size={12} />,
    cls: 'badge-review',
  },
  missing: {
    label: 'Missing',
    icon: <XCircle size={12} />,
    cls: 'badge-missing',
  },
  approved: {
    label: 'Approved by you',
    icon: <CircleCheck size={12} />,
    cls: 'badge-approved',
  },
  rejected: {
    label: 'Rejected',
    icon: <XCircle size={12} />,
    cls: 'badge-rejected',
  },
};

export function StatusBadge({ status }: { status: MappingStatus }) {
  const cfg = STATUS_CONFIG[status];
  return (
    <span className={`badge ${cfg.cls}`}>
      {cfg.icon}
      {cfg.label}
    </span>
  );
}

export function BatchStatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    pending: { label: 'Pending', cls: 'badge-review', icon: <Loader2 size={12} className="animate-spin" /> },
    running: { label: 'Processing', cls: 'badge-processing', icon: <Loader2 size={12} style={{ animation: 'spin 0.7s linear infinite' }} /> },
    done: { label: 'Done', cls: 'badge-auto', icon: <CheckCircle2 size={12} /> },
    failed: { label: 'Failed', cls: 'badge-missing', icon: <XCircle size={12} /> },
    cancelled: { label: 'Cancelled', cls: 'badge-rejected', icon: <XCircle size={12} /> },
  };
  const cfg = map[status] ?? { label: status, cls: 'badge-processing', icon: null };
  return <span className={`badge ${cfg.cls}`}>{cfg.icon} {cfg.label}</span>;
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────
export function Skeleton({ w, h, style }: { w?: string | number; h?: string | number; style?: React.CSSProperties }) {
  return (
    <div
      className="skeleton"
      style={{ width: w ?? '100%', height: h ?? 16, ...style }}
    />
  );
}

export function TableSkeleton({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            {Array.from({ length: cols }).map((_, i) => (
              <th key={i}><Skeleton h={12} /></th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r}>
              {Array.from({ length: cols }).map((_, c) => (
                <td key={c}><Skeleton h={14} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Empty State ──────────────────────────────────────────────────────────────
export function EmptyState({
  icon, title, text, action,
}: {
  icon?: React.ReactNode;
  title: string;
  text?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state-icon">{icon}</div>}
      <div className="empty-state-title">{title}</div>
      {text && <p className="empty-state-text">{text}</p>}
      {action}
    </div>
  );
}

// ─── Error Banner ─────────────────────────────────────────────────────────────
export function ErrorBanner({
  title, message, onRetry, onDismiss,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}) {
  return (
    <div className="alert alert-error" role="alert">
      <XCircle size={18} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div className="alert-title">{title}</div>
        <div className="alert-body">{message}</div>
      </div>
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        {onRetry && (
          <button className="btn btn-sm btn-danger" onClick={onRetry}>Retry</button>
        )}
        {onDismiss && (
          <button className="btn btn-sm btn-ghost" onClick={onDismiss}>Dismiss</button>
        )}
      </div>
    </div>
  );
}

// ─── AI Error Banner (quota, 401, 503) ────────────────────────────────────────
export function AiErrorBanner({ onRetry }: { onRetry?: () => void }) {
  return (
    <div className="alert alert-warning" role="alert">
      <AlertCircle size={18} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div className="alert-title">AI service unavailable</div>
        <div className="alert-body">Your work is saved. This may be a temporary quota or network issue.</div>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        {onRetry && <button className="btn btn-sm btn-secondary" onClick={onRetry}>Retry</button>}
        <button className="btn btn-sm btn-ghost">Contact organizers</button>
      </div>
    </div>
  );
}

// ─── Spinner ─────────────────────────────────────────────────────────────────
export function Spinner({ size = 20 }: { size?: number }) {
  return (
    <div
      className="spinner"
      style={{ width: size, height: size }}
      role="status"
      aria-label="Loading"
    />
  );
}

// ─── Tooltip ─────────────────────────────────────────────────────────────────
export function Tooltip({ children, content }: { children: React.ReactNode; content: string }) {
  return (
    <div className="tooltip-wrapper">
      {children}
      <div className="tooltip-content" role="tooltip">{content}</div>
    </div>
  );
}
