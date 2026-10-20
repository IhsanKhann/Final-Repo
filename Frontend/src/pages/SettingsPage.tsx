import React, { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  User, Palette, Sliders, Bell, Shield, Database,
  HelpCircle, Upload, Trash2, Check, ArrowLeft, Sun,
  Moon, Laptop, Info, RefreshCw, Save, RotateCcw, AlertCircle,
  KeyRound
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { useToast } from '../context/AppContext';
import { getSettings, patchSettings } from '../api/client';
import type {
  ConfigSource, ConfigValue, ControlView, SecretView, SettingsPatch,
} from '../api/types';

type SettingsTab = 'profile' | 'appearance' | 'review' | 'notifications' | 'security' | 'data' | 'help';

// The two controls that decide the three lanes. Pulled out of the generic list because
// they are the live demonstration of a configurable business rule, and because they are
// the one pair with an ordering constraint the backend enforces.
const GATE_KEYS = ['gate_auto_threshold', 'gate_review_threshold'];

// Model routing. Shown together so an operator reads provider and model as one decision.
const MODEL_KEYS = ['provider', 'model', 'vision_model'];

// Four rows of data, two wire dialects — the provider ids the backend actually knows.
const PROVIDER_OPTIONS = ['openai', 'openrouter', 'google', 'anthropic'];

/**
 * What the resolver that answered was. The whole reason the config layer exists is that
 * an operator can see WHERE the value answering right now came from, so this is never
 * optional decoration.
 */
const SOURCE_COPY: Record<ConfigSource, string> = {
  session: 'Set for this session only.',
  db: 'Saved here. This store owns the value.',
  'env-seed': 'Seeded once from the environment; the store owns it now.',
  env: 'Read from the environment. Saving here takes ownership of it.',
  default: 'Nothing is stored — this is the stated default.',
  'last-known-good': 'The store was unreachable; this is the last value known to work.',
  unset: 'Never set, by any resolver.',
};

function SourceBadge({ source }: { source: ConfigSource }) {
  const muted = source === 'unset' || source === 'default';
  return (
    <span
      title={SOURCE_COPY[source] ?? source}
      style={{
        display: 'inline-block',
        padding: '1px 7px',
        borderRadius: 999,
        fontSize: '0.65rem',
        fontWeight: 700,
        letterSpacing: '0.02em',
        border: '1px solid var(--color-border)',
        background: muted ? 'transparent' : 'var(--color-accent-light)',
        color: muted ? 'var(--color-text-muted)' : 'var(--color-accent)',
        whiteSpace: 'nowrap',
      }}
    >
      {source}
    </span>
  );
}

/**
 * Presence and provenance of a credential — never its value. `SecretView` has no value
 * field on the wire, and `present: false` with `source: 'db'` is a different fact from
 * `source: 'unset'`: the first was deliberately cleared, the second was never set.
 */
function secretStateCopy(s: SecretView): { text: string; tone: 'ok' | 'warn' | 'muted' } {
  if (s.present) return { text: 'configured', tone: 'ok' };
  if (s.source === 'unset') return { text: 'not configured', tone: 'muted' };
  return { text: 'cleared — stored empty, chain stops here', tone: 'warn' };
}

export function SettingsPage() {
  const { user, updateProfile } = useAuth();
  const {
    themeMode, setThemeMode,
    density, setDensity,
    textSize, setTextSize,
    reduceMotion, setReduceMotion,
    dimDocuments, setDimDocuments,
    highContrast, setHighContrast,
  } = useTheme();
  const { addToast } = useToast();

  const [activeTab, setActiveTab] = useState<SettingsTab>('profile');
  const [mobileDrilled, setMobileDrilled] = useState(false);

  // Profile Form State
  const [name, setName] = useState(user?.name ?? 'Amina Khan');
  const [jobTitle, setJobTitle] = useState(user?.jobTitle ?? 'Senior ESG & Operational Analyst');
  const [timezone, setTimezone] = useState(user?.timezone ?? 'Asia/Karachi');
  const [language, setLanguage] = useState(user?.language ?? 'English (US)');
  const [dateFormat, setDateFormat] = useState(user?.dateFormat ?? 'YYYY-MM-DD');
  const [avatarPreview, setAvatarPreview] = useState<string | undefined>(user?.avatarUrl);
  const [avatarError, setAvatarError] = useState<string | null>(null);

  // Pipeline controls come from the backend config layer, not from local state. The only
  // local state is the operator's unsaved edit, keyed by control name: a key absent from
  // the draft was not touched, so a PATCH only ever carries what actually changed.
  const queryClient = useQueryClient();
  const {
    data: settings,
    isLoading: settingsLoading,
    isError: settingsError,
    error: settingsErrorObj,
    refetch: refetchSettings,
    isRefetching: settingsRefetching,
  } = useQuery({ queryKey: ['settings'], queryFn: getSettings });

  const [controlDraft, setControlDraft] = useState<Record<string, string>>({});
  const [secretDraft, setSecretDraft] = useState<Record<string, string>>({});

  // Notification settings
  const [notifBatchDone, setNotifBatchDone] = useState(true);
  const [notifReviewAlert, setNotifReviewAlert] = useState(true);
  const [notifWeeklyReport, setNotifWeeklyReport] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Avatar file upload handler with client-side validation
  const handleAvatarFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setAvatarError(null);
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate type: png, jpg, jpeg, webp
    const validTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'];
    if (!validTypes.includes(file.type)) {
      setAvatarError('Please upload a PNG, JPG, or WebP image file.');
      return;
    }

    // Validate size: max 2 MB
    const maxSize = 2 * 1024 * 1024; // 2MB
    if (file.size > maxSize) {
      setAvatarError(`Image is ${(file.size / (1024 * 1024)).toFixed(1)} MB. Maximum allowed size is 2 MB.`);
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      setAvatarPreview(reader.result as string);
      addToast({
        type: 'info',
        title: 'Photo Previewed',
        message: 'Click "Save changes" below to update your account avatar.',
      });
    };
    reader.readAsDataURL(file);
  };

  const handleRemoveAvatar = () => {
    setAvatarPreview(undefined);
    setAvatarError(null);
  };

  const handleSaveProfile = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      addToast({ type: 'warning', title: 'Name Required', message: 'Full name cannot be left blank.' });
      return;
    }

    updateProfile({
      name,
      jobTitle,
      timezone,
      language,
      dateFormat,
      avatarUrl: avatarPreview,
    });

    addToast({
      type: 'success',
      title: 'Profile Saved',
      message: 'Account details and regional settings were successfully updated.',
    });
  };

  const handleDiscardProfile = () => {
    setName(user?.name ?? '');
    setJobTitle(user?.jobTitle ?? '');
    setTimezone(user?.timezone ?? 'Asia/Karachi');
    setLanguage(user?.language ?? 'English (US)');
    setDateFormat(user?.dateFormat ?? 'YYYY-MM-DD');
    setAvatarPreview(user?.avatarUrl);
    setAvatarError(null);
    addToast({ type: 'info', title: 'Changes Discarded', message: 'Reverted to last saved profile.' });
  };

  // ─── Pipeline controls & credentials ───────────────────────────────────────

  const saveSettings = useMutation({
    mutationFn: (patch: SettingsPatch) => patchSettings(patch),
    onSuccess: (view) => {
      // The response is a fresh resolution, not an echo of what was written, so it is
      // the authoritative answer for what the next request will see.
      queryClient.setQueryData(['settings'], view);
      setControlDraft({});
      setSecretDraft({});
      addToast({
        type: 'success',
        title: view.updated.length ? 'Configuration Saved' : 'Nothing Written',
        message: view.updated.length
          ? `Wrote ${view.updated.join(', ')}. The next run resolves these from the store.`
          : 'The store accepted the request but wrote nothing.',
      });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: 'Configuration Rejected',
        message: err instanceof Error ? err.message : 'The settings endpoint refused the change.',
      });
    },
  });

  const controlsByKey: Record<string, ControlView> = {};
  (settings?.controls ?? []).forEach(c => { controlsByKey[c.key] = c; });

  /** The string currently in the field: the operator's edit if any, otherwise resolved. */
  const controlString = (c: ControlView): string =>
    controlDraft[c.key] ?? (c.value === null || c.value === undefined ? '' : String(c.value));

  const isDirty = (key: string) => Object.prototype.hasOwnProperty.call(controlDraft, key);

  /**
   * Cast by the shape of the declared default, because that is what the backend casts to.
   * An empty field stays the empty string and is never coerced to 0 — a stored "" is a
   * value that stops the resolution chain, and losing that would make a key unclearable.
   */
  const castForWire = (c: ControlView, raw: string): ConfigValue => {
    if (raw.trim() === '') return '';
    if (typeof c.default === 'number') {
      const n = Number(raw);
      return Number.isFinite(n) ? n : raw;
    }
    if (typeof c.default === 'boolean') return raw.trim().toLowerCase() === 'true';
    return raw;
  };

  const asNumber = (raw: string) => (raw.trim() === '' ? NaN : Number(raw));
  const autoRaw = controlsByKey['gate_auto_threshold'];
  const reviewRaw = controlsByKey['gate_review_threshold'];
  const autoValue = autoRaw ? asNumber(controlString(autoRaw)) : NaN;
  const reviewValue = reviewRaw ? asNumber(controlString(reviewRaw)) : NaN;

  const outOfUnitRange = (v: number) => !Number.isFinite(v) || v < 0 || v > 1;

  // Confidence is a float 0–1, never a percentage — and the backend raises if the review
  // threshold sits above the auto threshold, so refuse it here rather than round-trip a 500.
  const gateError: string | null = !autoRaw || !reviewRaw
    ? null
    : outOfUnitRange(autoValue)
      ? 'The auto threshold must be a number between 0 and 1.'
      : outOfUnitRange(reviewValue)
        ? 'The review threshold must be a number between 0 and 1.'
        : reviewValue > autoValue
          ? `The review threshold (${reviewValue}) is above the auto threshold (${autoValue}). That ordering would leave no review lane, and the engine refuses it.`
          : null;

  const pendingCount = Object.keys(controlDraft).length + Object.keys(secretDraft).length;

  const handleSavePipelineSettings = () => {
    if (gateError) {
      addToast({ type: 'warning', title: 'Thresholds Invalid', message: gateError });
      return;
    }
    const controls: Record<string, ConfigValue> = {};
    Object.entries(controlDraft).forEach(([key, raw]) => {
      const c = controlsByKey[key];
      if (c) controls[key] = castForWire(c, raw);
    });
    const secrets: Record<string, string> = { ...secretDraft };
    if (!Object.keys(controls).length && !Object.keys(secrets).length) {
      addToast({
        type: 'info',
        title: 'Nothing Changed',
        message: 'No control or credential was edited, so nothing was sent.',
      });
      return;
    }
    saveSettings.mutate({ controls, secrets });
  };

  const handleDiscardPipelineSettings = () => {
    setControlDraft({});
    setSecretDraft({});
  };

  /**
   * Clearing is its own action and sends "" on purpose. An operator who has revoked a key
   * upstream must be able to stop this store answering with it, and an empty string is the
   * only value that does that — env would otherwise keep seeding the old one.
   */
  const handleClearSecret = (id: string) => {
    saveSettings.mutate({ controls: {}, secrets: { [id]: '' } });
  };

  const renderControlRow = (c: ControlView, opts?: { invalid?: boolean }) => {
    const dirty = isDirty(c.key);
    const numeric = typeof c.default === 'number';
    const gate = GATE_KEYS.includes(c.key);
    const border = opts?.invalid
      ? '1px solid var(--color-danger, #dc2626)'
      : dirty
        ? '1px solid var(--color-accent)'
        : '1px solid var(--color-border)';

    return (
      <div
        key={c.key}
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 180px',
          gap: 14,
          alignItems: 'center',
          padding: '10px 0',
          borderTop: '1px solid var(--color-border)',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--color-text-primary)', fontFamily: 'ui-monospace, monospace' }}>
            {c.key}
          </div>
          <div
            style={{
              display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
              marginTop: 4, fontSize: '0.7rem', color: 'var(--color-text-muted)',
            }}
          >
            <SourceBadge source={c.source} />
            <span>env <code>{c.env_var}</code></span>
            <span>default <code>{c.default === '' ? '""' : String(c.default)}</code></span>
            {dirty && <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>unsaved</span>}
          </div>
        </div>

        {c.key === 'provider' ? (
          <select
            value={controlString(c)}
            onChange={e => setControlDraft(p => ({ ...p, [c.key]: e.target.value }))}
            aria-label={c.key}
            style={{ width: '100%', padding: '7px 10px', borderRadius: 6, border, fontSize: '0.8125rem' }}
          >
            {PROVIDER_OPTIONS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        ) : (
          <input
            type={numeric ? 'number' : 'text'}
            step={gate ? 0.01 : undefined}
            min={gate ? 0 : undefined}
            max={gate ? 1 : undefined}
            value={controlString(c)}
            onChange={e => setControlDraft(p => ({ ...p, [c.key]: e.target.value }))}
            aria-label={c.key}
            aria-invalid={opts?.invalid || undefined}
            placeholder="(empty)"
            style={{
              width: '100%', padding: '7px 10px', borderRadius: 6, border,
              fontSize: '0.8125rem', fontFamily: 'ui-monospace, monospace',
            }}
          />
        )}
      </div>
    );
  };


  const navItems = [
    { id: 'profile' as const, label: 'Profile', icon: <User size={16} />, badge: user ? undefined : 'Sign in' },
    { id: 'appearance' as const, label: 'Appearance', icon: <Palette size={16} /> },
    { id: 'review' as const, label: 'Review & Model', icon: <Sliders size={16} /> },
    { id: 'notifications' as const, label: 'Notifications', icon: <Bell size={16} /> },
    { id: 'security' as const, label: 'Security & SSO', icon: <Shield size={16} /> },
    { id: 'data' as const, label: 'Data Management', icon: <Database size={16} /> },
    { id: 'help' as const, label: 'Help & Support', icon: <HelpCircle size={16} /> },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 1080, margin: '0 auto' }}>
      {/* Page Title */}
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Settings & Account Portal
        </h1>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', marginTop: 4 }}>
          Manage your personal profile, workspace theme, extraction thresholds, and application preferences.
        </p>
      </div>

      {/* Main Settings Sub-Navigation & Content Layout */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', minHeight: 560 }}>
          {/* Left Sub-Navigation */}
          <nav
            style={{
              borderRight: '1px solid var(--color-border)',
              background: 'var(--color-surface-2)',
              padding: '14px 10px',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}
            aria-label="Settings sub-navigation"
          >
            {navItems.map(item => {
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  className={`nav-item ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    setActiveTab(item.id);
                    setMobileDrilled(true);
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '9px 12px',
                    borderRadius: 8,
                    border: 'none',
                    background: isActive ? 'var(--color-accent-light)' : 'transparent',
                    color: isActive ? 'var(--color-accent)' : 'var(--color-text-primary)',
                    fontWeight: isActive ? 600 : 500,
                    fontSize: '0.875rem',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    {item.icon}
                    <span>{item.label}</span>
                  </div>
                  {item.badge && (
                    <span className="badge badge-review" style={{ fontSize: '0.65rem' }}>
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Right Content Column (max-width 720px) */}
          <div style={{ padding: '24px 32px', maxWidth: 720, overflowY: 'auto' }}>
            {/* 1. PROFILE SUB-PAGE */}
            {activeTab === 'profile' && (
              <form onSubmit={handleSaveProfile} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div>
                  <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                    Personal Profile
                  </h2>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    Your identity within the enterprise data standardization workspace.
                  </p>
                </div>

                {/* Avatar upload & preview */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <div
                    style={{
                      width: 64,
                      height: 64,
                      borderRadius: '50%',
                      background: 'var(--color-accent)',
                      color: 'white',
                      fontWeight: 700,
                      fontSize: '1.25rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      overflow: 'hidden',
                      border: '2px solid var(--color-border)',
                      flexShrink: 0,
                    }}
                  >
                    {avatarPreview ? (
                      <img src={avatarPreview} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ) : (
                      name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()
                    )}
                  </div>

                  <div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/png,image/jpeg,image/jpg,image/webp"
                      style={{ display: 'none' }}
                      onChange={handleAvatarFileChange}
                    />
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => fileInputRef.current?.click()}
                        style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                      >
                        <Upload size={13} /> Change photo
                      </button>
                      {avatarPreview && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={handleRemoveAvatar}
                          style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--color-error)' }}
                        >
                          <Trash2 size={13} /> Remove
                        </button>
                      )}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginTop: 4 }}>
                      PNG, JPG or WebP (max 2 MB)
                    </div>
                    {avatarError && (
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-error)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                        <AlertCircle size={12} /> {avatarError}
                      </div>
                    )}
                  </div>
                </div>

                {/* Full name (required) */}
                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                    Full Name <span style={{ color: 'var(--color-error)' }}>*</span>
                  </label>
                  <input
                    type="text"
                    required
                    value={name}
                    onChange={e => setName(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.875rem' }}
                  />
                </div>

                {/* Email (read-only with SSO badge) */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                      Work Email Address
                    </label>
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                      Managed by your sign-in provider (SSO)
                    </span>
                  </div>
                  <input
                    type="email"
                    readOnly
                    value={user?.email ?? 'analyst@local'}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-surface-2)', color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}
                  />
                </div>

                {/* Job Title */}
                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                    Job Title / Role Designation
                  </label>
                  <input
                    type="text"
                    value={jobTitle}
                    onChange={e => setJobTitle(e.target.value)}
                    placeholder="e.g. Senior ESG Data Analyst"
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.875rem' }}
                  />
                </div>

                {/* Organization & Role (read-only with (?) tooltip) */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                      Organization (Tenant)
                    </label>
                    <input
                      type="text"
                      readOnly
                      value={user?.organization ?? ''}
                      style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-surface-2)', color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}
                    />
                  </div>

                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                      <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                        Assigned Role
                      </label>
                      <div className="tooltip-wrapper" title="Analyst: Upload & review. Reviewer: Approvals. Admin: Schema & model configuration.">
                        <HelpCircle size={14} color="var(--color-text-muted)" style={{ cursor: 'pointer' }} />
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', height: 38 }}>
                      <span className="badge badge-auto" style={{ fontSize: '0.8rem', padding: '4px 10px' }}>
                        {user?.role ?? 'Analyst'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Regional settings: Timezone, Language, Date Format */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                      Timezone
                    </label>
                    <select
                      value={timezone}
                      onChange={e => setTimezone(e.target.value)}
                      style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.8125rem' }}
                    >
                      <option value="Asia/Karachi">Asia/Karachi (PKT +05:00)</option>
                      <option value="UTC">UTC (Universal)</option>
                      <option value="America/New_York">America/New_York (EST)</option>
                      <option value="Europe/London">Europe/London (GMT/BST)</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                      Language
                    </label>
                    <select
                      value={language}
                      onChange={e => setLanguage(e.target.value)}
                      style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.8125rem' }}
                    >
                      <option value="English (US)">English (US)</option>
                      <option value="English (UK)">English (UK)</option>
                      <option value="Urdu (اردو)">Urdu (اردو)</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                      Date Format
                    </label>
                    <select
                      value={dateFormat}
                      onChange={e => setDateFormat(e.target.value)}
                      style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.8125rem' }}
                    >
                      <option value="YYYY-MM-DD">YYYY-MM-DD (ISO)</option>
                      <option value="DD/MM/YYYY">DD/MM/YYYY</option>
                      <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                    </select>
                  </div>
                </div>

                {/* Form Buttons */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, borderTop: '1px solid var(--color-border)', paddingTop: 16, marginTop: 8 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={handleDiscardProfile}
                  >
                    Discard changes
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                  >
                    <Save size={14} /> Save changes
                  </button>
                </div>
              </form>
            )}

            {/* 2. APPEARANCE SUB-PAGE */}
            {activeTab === 'appearance' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                <div>
                  <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                    Appearance & Ergonomics
                  </h2>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    Customize color themes, typography scaling, document contrast, and motion preferences.
                  </p>
                </div>

                {/* Theme Mode Preview Cards */}
                <div>
                  <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 10 }}>
                    Theme Mode (Applies Instantly)
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
                    {/* Light Preview Card */}
                    <div
                      onClick={() => setThemeMode('light')}
                      style={{
                        padding: 14,
                        borderRadius: 10,
                        border: `2px solid ${themeMode === 'light' ? 'var(--color-accent)' : 'var(--color-border)'}`,
                        background: '#ffffff',
                        color: '#0f172a',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease',
                        boxShadow: themeMode === 'light' ? '0 0 0 1px var(--color-accent)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: '0.85rem' }}>
                          <Sun size={15} color="#4f46e5" /> Light
                        </div>
                        {themeMode === 'light' && <Check size={16} color="#4f46e5" />}
                      </div>
                      <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <div style={{ width: '60%', height: 6, background: '#cbd5e1', borderRadius: 3 }} />
                        <div style={{ width: '85%', height: 6, background: '#4f46e5', borderRadius: 3 }} />
                      </div>
                    </div>

                    {/* Dark Preview Card */}
                    <div
                      onClick={() => setThemeMode('dark')}
                      style={{
                        padding: 14,
                        borderRadius: 10,
                        border: `2px solid ${themeMode === 'dark' ? 'var(--color-accent)' : 'var(--color-border)'}`,
                        background: '#121a2e',
                        color: '#f8fafc',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease',
                        boxShadow: themeMode === 'dark' ? '0 0 0 1px var(--color-accent)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: '0.85rem' }}>
                          <Moon size={15} color="#818cf8" /> Dark
                        </div>
                        {themeMode === 'dark' && <Check size={16} color="#818cf8" />}
                      </div>
                      <div style={{ background: '#1a2440', border: '1px solid #2a3552', borderRadius: 6, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <div style={{ width: '60%', height: 6, background: '#8a94ad', borderRadius: 3 }} />
                        <div style={{ width: '85%', height: 6, background: '#818cf8', borderRadius: 3 }} />
                      </div>
                    </div>

                    {/* System Auto Card */}
                    <div
                      onClick={() => setThemeMode('system')}
                      style={{
                        padding: 14,
                        borderRadius: 10,
                        border: `2px solid ${themeMode === 'system' ? 'var(--color-accent)' : 'var(--color-border)'}`,
                        background: 'linear-gradient(135deg, #ffffff 50%, #121a2e 50%)',
                        color: 'var(--color-text-primary)',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease',
                        boxShadow: themeMode === 'system' ? '0 0 0 1px var(--color-accent)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: '0.85rem', background: 'var(--color-surface)', padding: '2px 6px', borderRadius: 4 }}>
                          <Laptop size={15} color="var(--color-accent)" /> System
                        </div>
                        {themeMode === 'system' && <Check size={16} color="var(--color-accent)" />}
                      </div>
                      <div style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 6, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <div style={{ width: '60%', height: 6, background: 'var(--color-text-muted)', borderRadius: 3 }} />
                        <div style={{ width: '85%', height: 6, background: 'var(--color-accent)', borderRadius: 3 }} />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Density: Comfortable vs Compact */}
                <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
                  <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                    Information Density
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                    <label
                      style={{
                        padding: '10px 14px',
                        borderRadius: 8,
                        border: `1px solid ${density === 'comfortable' ? 'var(--color-accent)' : 'var(--color-border)'}`,
                        background: density === 'comfortable' ? 'var(--color-accent-light)' : 'var(--color-surface-2)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        cursor: 'pointer',
                        fontSize: '0.85rem',
                      }}
                    >
                      <input
                        type="radio"
                        name="density"
                        checked={density === 'comfortable'}
                        onChange={() => setDensity('comfortable')}
                      />
                      <div>
                        <strong>Comfortable</strong>
                        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Generous spacing for analysis</div>
                      </div>
                    </label>

                    <label
                      style={{
                        padding: '10px 14px',
                        borderRadius: 8,
                        border: `1px solid ${density === 'compact' ? 'var(--color-accent)' : 'var(--color-border)'}`,
                        background: density === 'compact' ? 'var(--color-accent-light)' : 'var(--color-surface-2)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        cursor: 'pointer',
                        fontSize: '0.85rem',
                      }}
                    >
                      <input
                        type="radio"
                        name="density"
                        checked={density === 'compact'}
                        onChange={() => setDensity('compact')}
                      />
                      <div>
                        <strong>Compact</strong>
                        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>High-density table rows</div>
                      </div>
                    </label>
                  </div>
                </div>

                {/* Text Size Scaling */}
                <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
                  <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                    Interface Text Size (Scales Whole App)
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                    {[
                      { id: 'default' as const, label: 'Default', size: '14px base' },
                      { id: 'large' as const, label: 'Large', size: '15px base' },
                      { id: 'extra-large' as const, label: 'Extra Large', size: '16px base' },
                    ].map(ts => (
                      <label
                        key={ts.id}
                        style={{
                          padding: '10px 14px',
                          borderRadius: 8,
                          border: `1px solid ${textSize === ts.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
                          background: textSize === ts.id ? 'var(--color-accent-light)' : 'var(--color-surface-2)',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 10,
                          cursor: 'pointer',
                          fontSize: '0.85rem',
                        }}
                      >
                        <input
                          type="radio"
                          name="textSize"
                          checked={textSize === ts.id}
                          onChange={() => setTextSize(ts.id)}
                        />
                        <div>
                          <strong>{ts.label}</strong>
                          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>{ts.size}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Accessibility Toggles: Motion, Dim Documents, High-Contrast */}
                <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div>
                      <strong style={{ fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>
                        Dim Documents in Dark Mode
                      </strong>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                        Applies gentle brightness dampening to white paper documents without inverting colors.
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={dimDocuments}
                      onChange={e => setDimDocuments(e.target.checked)}
                      style={{ width: 18, height: 18, cursor: 'pointer' }}
                    />
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div>
                      <strong style={{ fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>
                        High-Contrast Card Borders
                      </strong>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                        Increases divider and border contrast to meet enhanced WCAG AAA requirements.
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={highContrast}
                      onChange={e => setHighContrast(e.target.checked)}
                      style={{ width: 18, height: 18, cursor: 'pointer' }}
                    />
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div>
                      <strong style={{ fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>
                        Reduced Motion Animations
                      </strong>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                        Disables micro-interactions and transitions for vestibular comfort.
                      </div>
                    </div>
                    <select
                      value={reduceMotion}
                      onChange={e => setReduceMotion(e.target.value as any)}
                      style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.8rem' }}
                    >
                      <option value="system">Follow System OS</option>
                      <option value="on">Always On (Reduced)</option>
                      <option value="off">Off (Smooth Transitions)</option>
                    </select>
                  </div>
                </div>
              </div>
            )}

            {/* 3. PIPELINE CONTROLS & CREDENTIALS SUB-PAGE
                Backed by GET/PATCH /api/settings. Every value is shown with the source
                that resolved it, and no secret value is ever rendered — SecretView has
                no value field on the wire, and this page has no place to put one. */}
            {activeTab === 'review' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
                  <div>
                    <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                      Pipeline Controls & Credentials
                    </h2>
                    <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                      Resolved live by the backend config layer. Each value carries the source
                      that answered, and a saved value takes effect on the next run — no redeploy.
                    </p>
                  </div>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => { void refetchSettings(); }}
                    disabled={settingsRefetching}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}
                  >
                    <RefreshCw size={14} className={settingsRefetching ? 'animate-spin' : ''} /> Re-resolve
                  </button>
                </div>

                {settingsLoading && (
                  <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                    Resolving configuration…
                  </div>
                )}

                {settingsError && (
                  <div
                    className="card"
                    style={{
                      padding: '12px 14px', display: 'flex', gap: 10, alignItems: 'flex-start',
                      background: 'var(--color-warning-bg)', borderColor: 'var(--color-warning-border)',
                    }}
                  >
                    <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
                    <div style={{ fontSize: '0.8125rem' }}>
                      <strong>Could not read the configuration.</strong>
                      <div style={{ color: 'var(--color-text-secondary)', marginTop: 2 }}>
                        {settingsErrorObj instanceof Error ? settingsErrorObj.message : 'GET /api/settings did not answer.'}
                        {' '}Nothing was changed.
                      </div>
                    </div>
                  </div>
                )}

                {settings && (
                  <>
                    <div style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
                      tenant <code>{settings.tenant_id}</code> · resolved{' '}
                      {new Date(settings.checked_at).toLocaleTimeString()}
                    </div>

                    {/* ── The gate: two thresholds, three lanes ─────────────────── */}
                    <section>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Sliders size={15} style={{ color: 'var(--color-accent)' }} />
                        <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                          Ambiguity gate
                        </h3>
                      </div>
                      <p style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', marginTop: 4, lineHeight: 1.5 }}>
                        Confidence is a float between 0 and 1, not a percentage. A field at or above
                        the auto threshold resolves on its own; a field between the two goes to review;
                        a field below the review threshold is recorded as <code>missing</code> rather
                        than guessed. These are stated defaults, not calibrated values.
                      </p>

                      {autoRaw ? renderControlRow(autoRaw, { invalid: !!gateError }) : null}
                      {reviewRaw ? renderControlRow(reviewRaw, { invalid: !!gateError }) : null}

                      {gateError && (
                        <div
                          style={{
                            display: 'flex', gap: 8, alignItems: 'flex-start', marginTop: 10,
                            padding: '9px 11px', borderRadius: 6,
                            background: 'var(--color-warning-bg)',
                            border: '1px solid var(--color-warning-border)',
                            fontSize: '0.75rem', color: 'var(--color-text-primary)',
                          }}
                          role="alert"
                        >
                          <AlertCircle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                          <span>{gateError}</span>
                        </div>
                      )}

                      {!gateError && Number.isFinite(autoValue) && Number.isFinite(reviewValue) && (
                        <div style={{ marginTop: 10, fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>
                          auto ≥ {autoValue} · review {reviewValue} – {autoValue} · missing &lt; {reviewValue}
                        </div>
                      )}
                    </section>

                    {/* ── Model routing ─────────────────────────────────────────── */}
                    <section>
                      <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                        Model routing
                      </h3>
                      <p style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', marginTop: 4 }}>
                        A listed provider is not necessarily a reachable one — the Health page reports
                        whether the chosen pair can actually answer.
                      </p>
                      {MODEL_KEYS.map(k => controlsByKey[k]).filter(Boolean).map(c => renderControlRow(c))}
                    </section>

                    {/* ── Everything else the registry declares ─────────────────── */}
                    <section>
                      <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                        Run limits & pack selection
                      </h3>
                      <p style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', marginTop: 4 }}>
                        Every remaining control the backend declares. Nothing here is invented by the
                        UI — an unrecognised name is refused by the endpoint before anything is written.
                      </p>
                      {settings.controls
                        .filter(c => !GATE_KEYS.includes(c.key) && !MODEL_KEYS.includes(c.key))
                        .map(c => renderControlRow(c))}
                    </section>

                    {/* ── Credentials: presence and provenance only ─────────────── */}
                    <section>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <KeyRound size={15} style={{ color: 'var(--color-accent)' }} />
                        <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                          Credentials
                        </h3>
                      </div>
                      <p style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', marginTop: 4, lineHeight: 1.5 }}>
                        A stored key is never sent back, so none can be displayed here — only whether
                        one is present and which resolver owns it. Clearing a key stores an empty
                        value, which deliberately stops the chain instead of letting the environment
                        seed the old one again.
                      </p>

                      {settings.secrets.map(s => {
                        const state = secretStateCopy(s);
                        const draft = secretDraft[s.id] ?? '';
                        const tone = state.tone === 'ok'
                          ? 'var(--color-success, #16a34a)'
                          : state.tone === 'warn'
                            ? 'var(--color-warning, #d97706)'
                            : 'var(--color-text-muted)';
                        return (
                          <div
                            key={s.id}
                            style={{
                              display: 'grid', gridTemplateColumns: '1fr 180px auto', gap: 10,
                              alignItems: 'center', padding: '10px 0',
                              borderTop: '1px solid var(--color-border)',
                            }}
                          >
                            <div style={{ minWidth: 0 }}>
                              <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--color-text-primary)', fontFamily: 'ui-monospace, monospace' }}>
                                {s.id}
                              </div>
                              <div
                                style={{
                                  display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
                                  marginTop: 4, fontSize: '0.7rem', color: 'var(--color-text-muted)',
                                }}
                              >
                                <SourceBadge source={s.source} />
                                <span style={{ color: tone, fontWeight: 600 }}>{state.text}</span>
                                {s.env_var && <span>seed <code>{s.env_var}</code></span>}
                                {draft !== '' && <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>unsaved</span>}
                              </div>
                            </div>

                            <input
                              type="password"
                              value={draft}
                              autoComplete="new-password"
                              placeholder={s.present ? 'Replace key…' : 'Paste key…'}
                              aria-label={`New value for ${s.id}`}
                              onChange={e => setSecretDraft(p => ({ ...p, [s.id]: e.target.value }))}
                              style={{
                                width: '100%', padding: '7px 10px', borderRadius: 6,
                                border: draft !== '' ? '1px solid var(--color-accent)' : '1px solid var(--color-border)',
                                fontSize: '0.8125rem',
                              }}
                            />

                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => handleClearSecret(s.id)}
                              disabled={saveSettings.isPending || (!s.present && s.source === 'unset')}
                              title="Store an empty value, stopping the resolution chain for this key"
                              style={{ display: 'flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap' }}
                            >
                              <Trash2 size={13} /> Clear
                            </button>
                          </div>
                        );
                      })}
                    </section>

                    <div
                      style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        gap: 12, flexWrap: 'wrap',
                        borderTop: '1px solid var(--color-border)', paddingTop: 16,
                      }}
                    >
                      <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                        {pendingCount === 0
                          ? 'No unsaved changes.'
                          : `${pendingCount} unsaved change${pendingCount === 1 ? '' : 's'}. Only edited keys are sent.`}
                      </span>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={handleDiscardPipelineSettings}
                          disabled={pendingCount === 0 || saveSettings.isPending}
                          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                        >
                          <RotateCcw size={13} /> Discard
                        </button>
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={handleSavePipelineSettings}
                          disabled={pendingCount === 0 || !!gateError || saveSettings.isPending}
                          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                        >
                          <Save size={13} /> {saveSettings.isPending ? 'Saving…' : 'Save configuration'}
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* 4. NOTIFICATIONS SUB-PAGE */}
            {activeTab === 'notifications' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div>
                  <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                    Notification Preferences
                  </h2>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    Manage pipeline completion alerts and human review queue notifications.
                  </p>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}>
                    <div>
                      <strong style={{ fontSize: '0.875rem' }}>Batch Processing Complete</strong>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Send notification when an ingestion run finishes</div>
                    </div>
                    <input
                      type="checkbox"
                      checked={notifBatchDone}
                      onChange={e => setNotifBatchDone(e.target.checked)}
                      style={{ width: 18, height: 18 }}
                    />
                  </label>

                  <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}>
                    <div>
                      <strong style={{ fontSize: '0.875rem' }}>Review Queue High Volume</strong>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Alert when flagged fields exceed 10 items</div>
                    </div>
                    <input
                      type="checkbox"
                      checked={notifReviewAlert}
                      onChange={e => setNotifReviewAlert(e.target.checked)}
                      style={{ width: 18, height: 18 }}
                    />
                  </label>

                  <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}>
                    <div>
                      <strong style={{ fontSize: '0.875rem' }}>Weekly AI Accuracy Digest</strong>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>Summary of continuous learning improvements</div>
                    </div>
                    <input
                      type="checkbox"
                      checked={notifWeeklyReport}
                      onChange={e => setNotifWeeklyReport(e.target.checked)}
                      style={{ width: 18, height: 18 }}
                    />
                  </label>
                </div>
              </div>
            )}

            {/* 5. SECURITY SUB-PAGE */}
            {activeTab === 'security' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div>
                  <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                    Security & SSO Credentials
                  </h2>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    Authentication standards and compliance policies.
                  </p>
                </div>

                <div style={{ background: 'var(--color-surface-2)', padding: '14px 16px', borderRadius: 8, border: '1px solid var(--color-border)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-success)', fontWeight: 600, fontSize: '0.875rem' }}>
                    <Shield size={16} /> Enterprise SSO Active (SAML 2.0 / OIDC)
                  </div>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-secondary)', marginTop: 6 }}>
                    Authentication tokens are never stored in browser local storage. Sessions are managed through secure HTTP-only cookies in compliance with SOC-2 and ISO 27001 standards.
                  </p>
                </div>

                <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                  Active Session: <strong>analyst-web-session-9842</strong> • IP: 192.168.1.45 (Islamabad, PK)
                </div>
              </div>
            )}

            {/* 6. DATA MANAGEMENT SUB-PAGE */}
            {activeTab === 'data' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div>
                  <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                    Data Store Management
                  </h2>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    Where this instance keeps its records.
                  </p>
                </div>

                {/* The "Reset Mock Demo Store" button lived here. It claimed to
                    re-populate Mining, Shipping and Finance documents and learned rules,
                    and did nothing at all except show a toast saying it had. A control
                    that reports success for work it never did is worse than no control:
                    it teaches an operator to trust a screen that cannot be trusted. */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'var(--color-surface-2)', borderRadius: 8, border: '1px solid var(--color-border)' }}>
                  <div>
                    <strong style={{ fontSize: '0.875rem' }}>Records live on the server</strong>
                    <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                      Batches, mappings and the evidence ledger are append-only and are not
                      resettable from this screen. Upload a new batch to add to them.
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* 7. HELP SUB-PAGE */}
            {activeTab === 'help' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div>
                  <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                    Help & Workspace Support
                  </h2>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    Guides, API references, and quick assistance for analysts.
                  </p>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <a
                    href="/help"
                    className="card"
                    style={{ padding: '14px 18px', textDecoration: 'none', color: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                  >
                    <div>
                      <strong style={{ fontSize: '0.9rem' }}>Comprehensive Documentation</strong>
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                        Pipeline specifications, schema pack formats, and keyboard controls.
                      </div>
                    </div>
                    <HelpCircle size={18} color="var(--color-accent)" />
                  </a>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
