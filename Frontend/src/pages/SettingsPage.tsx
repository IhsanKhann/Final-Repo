import React, { useState } from 'react';
import {
  Settings, Save, Cpu, Sliders, Database,
  ShieldCheck, AlertCircle, RefreshCw
} from 'lucide-react';
import { useToast } from '../context/AppContext';

export function SettingsPage() {
  const { addToast } = useToast();

  const [threshold, setThreshold] = useState(90);
  const [model, setModel] = useState('gemini-1.5-pro');
  const [ocrEngine, setOcrEngine] = useState('document-ai');
  const [autoLearn, setAutoLearn] = useState(true);

  const handleSave = () => {
    addToast({
      type: 'success',
      title: 'Preferences Saved',
      message: 'System parameters and model thresholds have been updated.',
    });
  };

  const handleResetData = () => {
    addToast({
      type: 'info',
      title: 'Demo Data Reset',
      message: 'Mock store re-initialized to default showcase state.',
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 840, margin: '0 auto' }}>
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          System & Pipeline Settings
        </h1>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
          Adjust AI reasoning model configurations, confidence gate thresholds, and continuous learning parameters.
        </p>
      </div>

      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Cpu size={18} color="var(--color-accent)" />
            <h2 className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>
              AI Model & Extraction Engine
            </h2>
          </div>
        </div>

        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div>
            <label style={{ display: 'block', fontWeight: 600, fontSize: '0.875rem', marginBottom: 6 }}>
              Semantic Extraction Model
            </label>
            <select
              value={model}
              onChange={e => setModel(e.target.value)}
              style={{
                width: '100%',
                maxWidth: 420,
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid var(--color-border)',
                background: 'var(--color-surface)',
                fontSize: '0.875rem',
              }}
            >
              <option value="gemini-1.5-pro">Google Gemini 1.5 Pro (Recommended - High reasoning)</option>
              <option value="gemini-1.5-flash">Google Gemini 1.5 Flash (Ultra-low latency)</option>
              <option value="gemini-2.0-flash">Google Gemini 2.0 Flash</option>
            </select>
            <p style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginTop: 4 }}>
              Used by Mapping Agent to understand messy table layouts and semantic synonym alignment.
            </p>
          </div>

          <div>
            <label style={{ display: 'block', fontWeight: 600, fontSize: '0.875rem', marginBottom: 6 }}>
              OCR / Layout Engine
            </label>
            <select
              value={ocrEngine}
              onChange={e => setOcrEngine(e.target.value)}
              style={{
                width: '100%',
                maxWidth: 420,
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid var(--color-border)',
                background: 'var(--color-surface)',
                fontSize: '0.875rem',
              }}
            >
              <option value="document-ai">Google Cloud Document AI (Specialized Table Parser)</option>
              <option value="tesseract">Local Tesseract OCR</option>
              <option value="pdfjs">Native PDF Vector Text Extractor</option>
            </select>
          </div>

          <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
            <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>
                Auto-Approval Confidence Threshold: <strong style={{ color: 'var(--color-accent)' }}>{threshold}%</strong>
              </span>
              <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                Fields ≥ {threshold}% bypass human review
              </span>
            </label>
            <input
              type="range"
              min="50"
              max="99"
              value={threshold}
              onChange={e => setThreshold(Number(e.target.value))}
              style={{ width: '100%', maxWidth: 420 }}
            />
          </div>

          <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.875rem' }}>Continuous Human Feedback Learning</div>
              <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                Store approved manual corrections into memory vectors to improve subsequent batch accuracy.
              </div>
            </div>
            <input
              type="checkbox"
              checked={autoLearn}
              onChange={e => setAutoLearn(e.target.checked)}
              style={{ width: 18, height: 18, cursor: 'pointer' }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleResetData}
            >
              <RefreshCw size={14} /> Re-seed Demo Data
            </button>

            <button
              className="btn btn-primary"
              onClick={handleSave}
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <Save size={15} /> Save Changes
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
