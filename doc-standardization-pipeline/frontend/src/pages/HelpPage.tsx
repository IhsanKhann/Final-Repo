import React from 'react';
import {
  HelpCircle, BookOpen, Command, Cpu, Layers,
  ShieldCheck, RefreshCw, CheckCircle2, ArrowRight
} from 'lucide-react';

export function HelpPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 880, margin: '0 auto' }}>
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Documentation & Platform Guide
        </h1>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
          Learn how DataSync extracts, standardizes, and validates heterogeneous enterprise documents into canonical schemas.
        </p>
      </div>

      {/* Overview Card */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <BookOpen size={18} color="var(--color-accent)" />
            <h2 className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>
              End-to-End Pipeline Architecture
            </h2>
          </div>
        </div>
        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: '0.875rem', lineHeight: 1.6, color: 'var(--color-text-secondary)' }}>
          <p>
            Enterprise organizations handle thousands of disparate filings, reports, and spreadsheets from diverse suppliers and partners. <strong>DataSync</strong> eliminates manual data entry by orchestrating a 5-stage autonomous agent pipeline:
          </p>

          <ol style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <li>
              <strong style={{ color: 'var(--color-text-primary)' }}>Ingestion Agent:</strong> Computes document fingerprints (SHA-256), validates MIME boundaries, and parses multi-sheet Excel files or web DOM structures.
            </li>
            <li>
              <strong style={{ color: 'var(--color-text-primary)' }}>OCR & Layout Agent (Google Document AI):</strong> Detects spatial coordinates, column alignments, cell headers, and bounding boxes.
            </li>
            <li>
              <strong style={{ color: 'var(--color-text-primary)' }}>Mapping Agent (Gemini 1.5):</strong> Understands domain synonyms (e.g. recognizing "Nickel output" matches canonical <code>production_t</code>) and computes a statistical confidence metric.
            </li>
            <li>
              <strong style={{ color: 'var(--color-text-primary)' }}>Normalization Agent:</strong> Executes deterministic mathematical unit conversions (e.g., converting pounds into metric tonnes or currencies using exchange rates).
            </li>
            <li>
              <strong style={{ color: 'var(--color-text-primary)' }}>Validation Agent:</strong> Enforces business sanity rules (non-negative production, threshold warnings) and surfaces ambiguous items to the Human Review Queue.
            </li>
          </ol>
        </div>
      </div>

      {/* Keyboard Shortcuts Reference */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Command size={18} color="var(--color-accent)" />
            <h2 className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>
              Review Screen Hotkeys
            </h2>
          </div>
        </div>
        <div className="card-body">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
            <div style={{ padding: 12, background: 'var(--color-surface-2)', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
              <kbd style={{ background: 'var(--color-surface)', padding: '4px 10px', borderRadius: 6, border: '1px solid var(--color-border)', fontWeight: 700 }}>A</kbd>
              <span style={{ fontSize: '0.85rem' }}>Accept current field</span>
            </div>
            <div style={{ padding: 12, background: 'var(--color-surface-2)', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
              <kbd style={{ background: 'var(--color-surface)', padding: '4px 10px', borderRadius: 6, border: '1px solid var(--color-border)', fontWeight: 700 }}>R</kbd>
              <span style={{ fontSize: '0.85rem' }}>Reject mapping</span>
            </div>
            <div style={{ padding: 12, background: 'var(--color-surface-2)', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
              <kbd style={{ background: 'var(--color-surface)', padding: '4px 10px', borderRadius: 6, border: '1px solid var(--color-border)', fontWeight: 700 }}>E</kbd>
              <span style={{ fontSize: '0.85rem' }}>Edit value / unit</span>
            </div>
            <div style={{ padding: 12, background: 'var(--color-surface-2)', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
              <kbd style={{ background: 'var(--color-surface)', padding: '4px 10px', borderRadius: 6, border: '1px solid var(--color-border)', fontWeight: 700 }}>↓ / ↑</kbd>
              <span style={{ fontSize: '0.85rem' }}>Next / Prev field</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
