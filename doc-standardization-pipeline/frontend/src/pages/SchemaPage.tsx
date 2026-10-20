import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Layers, Plus, Check, ShieldCheck, RefreshCw,
  Tag, Code2, AlertTriangle, XCircle, Sparkles, Save
} from 'lucide-react';
import { getPacks, updatePack } from '../api/client';
import type { SchemaPack, SchemaField, UnitConversion, BusinessRule } from '../api/types';
import { useToast, useActivePack } from '../context/AppContext';

export function SchemaPage() {
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const { activePack, setActivePack } = useActivePack();

  const [activeTab, setActiveTab] = useState<'fields' | 'conversions' | 'rules'>('fields');
  const [newSynonym, setNewSynonym] = useState<Record<string, string>>({});
  const [isAddingField, setIsAddingField] = useState(false);
  const [newFieldName, setNewFieldName] = useState('');
  const [newFieldLabel, setNewFieldLabel] = useState('');
  const [newFieldType, setNewFieldType] = useState<'number' | 'string' | 'date'>('number');
  const [newFieldUnit, setNewFieldUnit] = useState('');

  const { data: packs, isLoading } = useQuery({
    queryKey: ['packs'],
    queryFn: getPacks,
  });

  const currentPack = packs?.find(p => p.id === activePack) ?? packs?.[0];

  const updatePackMutation = useMutation({
    mutationFn: (updated: Partial<SchemaPack>) => updatePack(currentPack!.id, updated),
    onSuccess: (savedPack) => {
      queryClient.setQueryData(['packs'], (old: SchemaPack[] | undefined) => {
        if (!old) return [savedPack];
        return old.map(p => p.id === savedPack.id ? savedPack : p);
      });
      addToast({
        type: 'success',
        title: 'Schema Updated',
        message: `Saved configuration for ${savedPack.name} ${savedPack.version}.`,
      });
    },
  });

  const handleAddSynonym = (fieldName: string) => {
    const val = newSynonym[fieldName]?.trim();
    if (!val || !currentPack) return;

    const updatedFields = currentPack.fields.map(f => {
      if (f.name === fieldName && !f.synonyms.includes(val.toLowerCase())) {
        return { ...f, synonyms: [...f.synonyms, val.toLowerCase()] };
      }
      return f;
    });

    updatePackMutation.mutate({ fields: updatedFields });
    setNewSynonym(prev => ({ ...prev, [fieldName]: '' }));
  };

  const handleRemoveSynonym = (fieldName: string, synToRemove: string) => {
    if (!currentPack) return;
    const updatedFields = currentPack.fields.map(f => {
      if (f.name === fieldName) {
        return { ...f, synonyms: f.synonyms.filter(s => s !== synToRemove) };
      }
      return f;
    });
    updatePackMutation.mutate({ fields: updatedFields });
  };

  const handleCreateField = () => {
    if (!newFieldName.trim() || !newFieldLabel.trim() || !currentPack) return;

    const newField: SchemaField = {
      name: newFieldName.trim().toLowerCase().replace(/\s+/g, '_'),
      label: newFieldLabel.trim(),
      type: newFieldType,
      unit: newFieldUnit.trim() || undefined,
      required: false,
      synonyms: [newFieldLabel.trim().toLowerCase()],
    };

    updatePackMutation.mutate({ fields: [...currentPack.fields, newField] });
    setIsAddingField(false);
    setNewFieldName('');
    setNewFieldLabel('');
    setNewFieldUnit('');
  };

  if (isLoading || !currentPack) {
    return <div style={{ padding: 32, textAlign: 'center' }}>Loading schema pack definitions…</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 1040, margin: '0 auto' }}>
      {/* Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            Schema Packs & Normalization Rules
          </h1>
          <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
            Configure canonical target fields, AI synonym matching vectors, unit transformations, and validation constraints.
          </p>
        </div>

        {/* Pack Selector Tabs */}
        <div style={{ display: 'flex', gap: 8 }}>
          {(packs ?? []).map(p => (
            <button
              key={p.id}
              className={`btn btn-sm ${activePack === p.id ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setActivePack(p.id)}
            >
              <Layers size={14} /> {p.name} {p.version}
            </button>
          ))}
        </div>
      </div>

      {/* Active Pack Summary Card */}
      <div className="card" style={{ padding: '18px 22px', background: 'var(--color-surface)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                {currentPack.name} Standardization Schema
              </h2>
              <span className="badge badge-auto">v{currentPack.version}</span>
            </div>
            <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem', marginTop: 4 }}>
              {currentPack.description || 'Enterprise domain standard schema definition'}
            </p>
          </div>

          <div style={{ display: 'flex', gap: 16, fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
            <div><strong style={{ color: 'var(--color-text-primary)' }}>{currentPack.fields.length}</strong> Target Fields</div>
            <div>•</div>
            <div><strong style={{ color: 'var(--color-text-primary)' }}>{currentPack.conversions.length}</strong> Unit Rules</div>
            <div>•</div>
            <div><strong style={{ color: 'var(--color-text-primary)' }}>{currentPack.rules.length}</strong> Business Rules</div>
          </div>
        </div>
      </div>

      {/* Sub-Tabs: Fields, Conversions, Rules */}
      <div className="card">
        <div style={{ display: 'flex', borderBottom: '1px solid var(--color-border)', padding: '0 16px' }}>
          <button
            className="tab-button"
            style={{
              padding: '14px 18px',
              border: 'none',
              background: 'transparent',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
              color: activeTab === 'fields' ? 'var(--color-accent)' : 'var(--color-text-muted)',
              borderBottom: activeTab === 'fields' ? '2px solid var(--color-accent)' : '2px solid transparent',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
            onClick={() => setActiveTab('fields')}
          >
            <Tag size={15} /> Fields & Synonym Vocabulary ({currentPack.fields.length})
          </button>
          <button
            className="tab-button"
            style={{
              padding: '14px 18px',
              border: 'none',
              background: 'transparent',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
              color: activeTab === 'conversions' ? 'var(--color-accent)' : 'var(--color-text-muted)',
              borderBottom: activeTab === 'conversions' ? '2px solid var(--color-accent)' : '2px solid transparent',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
            onClick={() => setActiveTab('conversions')}
          >
            <Sparkles size={15} /> Unit Conversions ({currentPack.conversions.length})
          </button>
          <button
            className="tab-button"
            style={{
              padding: '14px 18px',
              border: 'none',
              background: 'transparent',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
              color: activeTab === 'rules' ? 'var(--color-accent)' : 'var(--color-text-muted)',
              borderBottom: activeTab === 'rules' ? '2px solid var(--color-accent)' : '2px solid transparent',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
            onClick={() => setActiveTab('rules')}
          >
            <ShieldCheck size={15} /> Business Constraints ({currentPack.rules.length})
          </button>
        </div>

        <div className="card-body">
          {/* TAB 1: Fields */}
          {activeTab === 'fields' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
                  Gemini matches extracted labels to target fields using these semantic synonyms.
                </span>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setIsAddingField(v => !v)}
                  style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  <Plus size={14} /> Add Target Field
                </button>
              </div>

              {/* Add field inline form */}
              {isAddingField && (
                <div style={{ padding: 14, background: 'var(--color-surface-2)', borderRadius: 8, border: '1px solid var(--color-border)', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr) auto', gap: 10, alignItems: 'center' }}>
                  <input
                    type="text"
                    placeholder="Field name (e.g. gross_revenue)"
                    value={newFieldName}
                    onChange={e => setNewFieldName(e.target.value)}
                    style={{ padding: '6px 10px', fontSize: '0.8125rem', borderRadius: 6, border: '1px solid var(--color-border)' }}
                  />
                  <input
                    type="text"
                    placeholder="Display label (e.g. Gross Revenue)"
                    value={newFieldLabel}
                    onChange={e => setNewFieldLabel(e.target.value)}
                    style={{ padding: '6px 10px', fontSize: '0.8125rem', borderRadius: 6, border: '1px solid var(--color-border)' }}
                  />
                  <select
                    value={newFieldType}
                    onChange={e => setNewFieldType(e.target.value as any)}
                    style={{ padding: '6px 10px', fontSize: '0.8125rem', borderRadius: 6, border: '1px solid var(--color-border)' }}
                  >
                    <option value="number">Number</option>
                    <option value="string">String</option>
                    <option value="date">Date</option>
                  </select>
                  <input
                    type="text"
                    placeholder="Unit (e.g. $M or t)"
                    value={newFieldUnit}
                    onChange={e => setNewFieldUnit(e.target.value)}
                    style={{ padding: '6px 10px', fontSize: '0.8125rem', borderRadius: 6, border: '1px solid var(--color-border)' }}
                  />
                  <button className="btn btn-primary btn-sm" onClick={handleCreateField}>
                    Save
                  </button>
                </div>
              )}

              {/* Fields Table */}
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Target Field</th>
                      <th>Type & Unit</th>
                      <th>Requirement</th>
                      <th>Trained Semantic Synonyms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentPack.fields.map(field => (
                      <tr key={field.name}>
                        <td>
                          <div style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                            {field.label}
                          </div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', fontFamily: 'monospace' }}>
                            {field.name}
                          </div>
                        </td>
                        <td>
                          <span className="badge" style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
                            {field.type} {field.unit ? `(${field.unit})` : ''}
                          </span>
                        </td>
                        <td>
                          {field.required ? (
                            <span className="badge badge-missing" style={{ fontSize: '0.7rem' }}>Required</span>
                          ) : (
                            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Optional</span>
                          )}
                        </td>
                        <td>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
                            {field.synonyms.map(syn => (
                              <span
                                key={syn}
                                style={{
                                  background: 'var(--color-accent-light)',
                                  color: 'var(--color-accent)',
                                  fontSize: '0.75rem',
                                  padding: '2px 8px',
                                  borderRadius: 4,
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                }}
                              >
                                {syn}
                                <button
                                  type="button"
                                  onClick={() => handleRemoveSynonym(field.name, syn)}
                                  style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--color-accent)', padding: 0 }}
                                >
                                  ×
                                </button>
                              </span>
                            ))}

                            {/* Add Synonym inline */}
                            <div style={{ display: 'flex', gap: 4 }}>
                              <input
                                type="text"
                                placeholder="+ synonym"
                                value={newSynonym[field.name] || ''}
                                onChange={e => setNewSynonym(prev => ({ ...prev, [field.name]: e.target.value }))}
                                onKeyDown={e => { if (e.key === 'Enter') handleAddSynonym(field.name); }}
                                style={{
                                  fontSize: '0.75rem',
                                  padding: '2px 6px',
                                  borderRadius: 4,
                                  border: '1px solid var(--color-border)',
                                  width: 90,
                                }}
                              />
                            </div>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 2: Unit Conversions */}
          {activeTab === 'conversions' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
                Automatic deterministic conversions executed by the Normalization Agent when source units differ from target schema standards.
              </div>

              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Rule ID</th>
                      <th>From Unit</th>
                      <th>Target Unit</th>
                      <th>Factor Multiplier</th>
                      <th>Mathematical Transformation Formula</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentPack.conversions.map(conv => (
                      <tr key={conv.id}>
                        <td style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--color-accent)' }}>
                          {conv.id}
                        </td>
                        <td><strong>{conv.from_unit}</strong></td>
                        <td><strong>{conv.to_unit}</strong></td>
                        <td style={{ fontFamily: 'monospace' }}>{conv.factor}</td>
                        <td>
                          <span style={{ background: 'var(--color-surface-2)', padding: '3px 8px', borderRadius: 4, fontFamily: 'monospace', fontSize: '0.8rem' }}>
                            {conv.formula || `value × ${conv.factor}`}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 3: Business Rules */}
          {activeTab === 'rules' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
                Auditing constraints evaluated after extraction. Deviations trigger flags in the human review queue.
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {currentPack.rules.map(rule => (
                  <div
                    key={rule.id}
                    style={{
                      padding: 14,
                      background: 'var(--color-surface-2)',
                      borderRadius: 8,
                      border: '1px solid var(--color-border)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>{rule.name}</span>
                        <span className={`badge ${rule.action === 'reject' ? 'badge-rejected' : 'badge-review'}`}>
                          {rule.action.toUpperCase()}
                        </span>
                      </div>
                      <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', marginTop: 4 }}>
                        {rule.description}
                      </p>
                    </div>

                    <div style={{ background: 'var(--color-surface)', padding: '6px 12px', borderRadius: 6, border: '1px solid var(--color-border)', fontFamily: 'monospace', fontSize: '0.8125rem' }}>
                      {rule.field}: <code>{rule.condition}</code>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
