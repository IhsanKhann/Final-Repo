import React, { useState, useRef } from 'react';
import {
  User, Palette, Sliders, Bell, Shield, Database,
  HelpCircle, Upload, Trash2, Check, ArrowLeft, Sun,
  Moon, Laptop, Info, RefreshCw, Save, RotateCcw, AlertCircle
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { useToast } from '../context/AppContext';

type SettingsTab = 'profile' | 'appearance' | 'review' | 'notifications' | 'security' | 'data' | 'help';

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

  // Review & AI Pipeline Settings State
  const [threshold, setThreshold] = useState(90);
  const [model, setModel] = useState('gemini-1.5-pro');
  const [ocrEngine, setOcrEngine] = useState('document-ai');
  const [autoLearn, setAutoLearn] = useState(true);

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

  const handleSaveReviewSettings = () => {
    addToast({
      type: 'success',
      title: 'Pipeline Configured',
      message: `Confidence threshold set to ${threshold}% with ${model}.`,
    });
  };

  const handleResetDemoData = () => {
    addToast({
      type: 'info',
      title: 'Demo Store Re-initialized',
      message: 'All mock documents, mappings, and learned corrections reset.',
    });
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
                    value={user?.email ?? 'amina.khan@acmemining.com'}
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
                      value={user?.organization ?? 'Acme Mining & Metals Global'}
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

            {/* 3. REVIEW & MODEL SUB-PAGE */}
            {activeTab === 'review' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div>
                  <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                    Review & Model Settings
                  </h2>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    Tune Gemini model extraction parameters and automated acceptance criteria.
                  </p>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                    Reasoning AI Model
                  </label>
                  <select
                    value={model}
                    onChange={e => setModel(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.875rem' }}
                  >
                    <option value="gemini-1.5-pro">Google Gemini 1.5 Pro (Recommended - Deep document reasoning)</option>
                    <option value="gemini-1.5-flash">Google Gemini 1.5 Flash (Ultra-fast latency)</option>
                    <option value="gemini-2.0-flash">Google Gemini 2.0 Flash</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                    OCR & Spatial Table Parser
                  </label>
                  <select
                    value={ocrEngine}
                    onChange={e => setOcrEngine(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.875rem' }}
                  >
                    <option value="document-ai">Google Cloud Document AI (Specialized Table Parser)</option>
                    <option value="tesseract">Local Tesseract Engine</option>
                  </select>
                </div>

                <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
                  <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>
                      Auto-Approval Confidence Threshold: <strong style={{ color: 'var(--color-accent)' }}>{threshold}%</strong>
                    </span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                      Fields &ge; {threshold}% bypass manual review
                    </span>
                  </label>
                  <input
                    type="range"
                    min="50"
                    max="99"
                    value={threshold}
                    onChange={e => setThreshold(Number(e.target.value))}
                    style={{ width: '100%' }}
                  />
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
                  <button className="btn btn-primary btn-sm" onClick={handleSaveReviewSettings}>
                    Save Model Parameters
                  </button>
                </div>
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
                    Re-seed mock demonstrations, reset local caches, or flush telemetry.
                  </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'var(--color-surface-2)', borderRadius: 8, border: '1px solid var(--color-border)' }}>
                  <div>
                    <strong style={{ fontSize: '0.875rem' }}>Reset Mock Demo Store</strong>
                    <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                      Re-populates default Mining, Shipping, and Finance mock documents and learned rules.
                    </div>
                  </div>
                  <button className="btn btn-secondary btn-sm" onClick={handleResetDemoData}>
                    <RefreshCw size={13} /> Reset Mock Data
                  </button>
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
