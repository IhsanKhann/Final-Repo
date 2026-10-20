import React, { createContext, useContext, useState, useCallback } from 'react';
import type { ReactNode } from 'react';

// ─── Toast System ────────────────────────────────────────────────────────────
export interface Toast {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  title: string;
  message?: string;
  action?: { label: string; onClick: () => void };
  duration?: number;
}

interface ToastContextValue {
  toasts: Toast[];
  addToast: (t: Omit<Toast, 'id'>) => string;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const addToast = useCallback((t: Omit<Toast, 'id'>) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts(prev => [...prev, { ...t, id }]);
    const dur = t.duration ?? 4000;
    if (dur > 0) setTimeout(() => removeToast(id), dur);
    return id;
  }, [removeToast]);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

// ─── Undo System ─────────────────────────────────────────────────────────────
interface UndoEntry {
  id: string;
  label: string;
  undo: () => void;
}

interface UndoContextValue {
  undoEntry: UndoEntry | null;
  pushUndo: (entry: Omit<UndoEntry, 'id'>) => void;
  clearUndo: () => void;
}

const UndoContext = createContext<UndoContextValue | null>(null);

export function UndoProvider({ children }: { children: ReactNode }) {
  const [undoEntry, setUndoEntry] = useState<UndoEntry | null>(null);

  const pushUndo = useCallback((entry: Omit<UndoEntry, 'id'>) => {
    const id = `undo-${Date.now()}`;
    setUndoEntry({ ...entry, id });
    // Auto-clear after 8 seconds
    setTimeout(() => setUndoEntry(prev => prev?.id === id ? null : prev), 8000);
  }, []);

  const clearUndo = useCallback(() => setUndoEntry(null), []);

  return (
    <UndoContext.Provider value={{ undoEntry, pushUndo, clearUndo }}>
      {children}
    </UndoContext.Provider>
  );
}

export function useUndo() {
  const ctx = useContext(UndoContext);
  if (!ctx) throw new Error('useUndo must be used within UndoProvider');
  return ctx;
}

// ─── Schema Pack Context ──────────────────────────────────────────────────────
interface PackContextValue {
  activePack: string;
  setActivePack: (id: string) => void;
}

const PackContext = createContext<PackContextValue | null>(null);

export function PackProvider({ children }: { children: ReactNode }) {
  const [activePack, setActivePack] = useState('mining-v1');
  return (
    <PackContext.Provider value={{ activePack, setActivePack }}>
      {children}
    </PackContext.Provider>
  );
}

export function useActivePack() {
  const ctx = useContext(PackContext);
  if (!ctx) throw new Error('useActivePack must be used within PackProvider');
  return ctx;
}
