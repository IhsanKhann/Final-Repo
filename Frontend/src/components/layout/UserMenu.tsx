import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  User, Settings, Sun, Moon, Laptop, Keyboard,
  HelpCircle, LogOut, LogIn, Check, Shield, ExternalLink
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';

export function UserMenu({ onOpenShortcuts }: { onOpenShortcuts?: () => void }) {
  const navigate = useNavigate();
  const { user, isAuthenticated, signOut, signIn } = useAuth();
  const { themeMode, setThemeMode } = useTheme();

  const [isOpen, setIsOpen] = useState(false);
  const [showSignInModal, setShowSignInModal] = useState(false);
  const [signInEmail, setSignInEmail] = useState('');
  const [signInRole, setSignInRole] = useState<'Analyst' | 'Reviewer' | 'Admin'>('Analyst');

  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  // Close on Escape and return focus
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (isOpen) {
          setIsOpen(false);
          buttonRef.current?.focus();
        }
        if (showSignInModal) {
          setShowSignInModal(false);
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, showSignInModal]);

  const initials = user?.name
    ? user.name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()
    : 'U';

  const handleSignInSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!signInEmail.trim()) return;
    signIn(signInEmail, signInRole);
    setShowSignInModal(false);
    setSignInEmail('');
  };

  // ⚠ NO AUTHENTICATION IS IMPLEMENTED. This sets a role in the browser only; it grants
  // nothing and the server neither sees it nor checks it. It used to sign you in as
  // invented people at an invented company (amina.khan@acmemining.com and two others),
  // which put fabricated identities on screen and implied an auth system that does not
  // exist. The roles stay because they are how we show a reviewer's view, but they are
  // now labelled as what they are.
  const handleQuickDemoSignIn = (role: 'Analyst' | 'Reviewer' | 'Admin') => {
    const emails = {
      Analyst: 'analyst@local',
      Reviewer: 'reviewer@local',
      Admin: 'admin@local',
    };
    const names = {
      Analyst: 'Amina Khan',
      Reviewer: 'Sarah Chen',
      Admin: 'Alex Vance (Lead)',
    };
    signIn(emails[role], role, names[role]);
    setShowSignInModal(false);
  };

  if (!isAuthenticated) {
    return (
      <>
        <button
          className="btn btn-primary btn-sm"
          onClick={() => setShowSignInModal(true)}
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <LogIn size={14} /> Sign In
        </button>

        {showSignInModal && (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0, 0, 0, 0.6)',
              backdropFilter: 'blur(3px)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 10000,
              padding: 16,
            }}
            onClick={() => setShowSignInModal(false)}
          >
            <div
              className="card"
              style={{ width: '100%', maxWidth: 420, padding: 24, boxShadow: 'var(--shadow-xl)' }}
              onClick={e => e.stopPropagation()}
            >
              <div style={{ textAlign: 'center', marginBottom: 20 }}>
                <div style={{ width: 44, height: 44, borderRadius: 10, background: 'var(--color-accent-light)', color: 'var(--color-accent)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 10 }}>
                  <Shield size={24} />
                </div>
                <h3 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                  Sign in to DataSync
                </h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', marginTop: 4 }}>
                  Cross-Source Data Standardization Analyst Workspace
                </p>
              </div>

              {/* Quick Persona Demo Logins */}
              <div style={{ marginBottom: 18 }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase', display: 'block', marginBottom: 4 }}>
                  View as role
                </span>
                <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', display: 'block', marginBottom: 8 }}>
                  Local only — no authentication is implemented and the server does not check this.
                </span>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleQuickDemoSignIn('Analyst')}
                  >
                    Analyst
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleQuickDemoSignIn('Reviewer')}
                  >
                    Reviewer
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleQuickDemoSignIn('Admin')}
                  >
                    Admin
                  </button>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '14px 0' }}>
                <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>or sign in with email</span>
                <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
              </div>

              <form onSubmit={handleSignInSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                    Work Email
                  </label>
                  <input
                    type="email"
                    required
                    placeholder="analyst@enterprise.com"
                    value={signInEmail}
                    onChange={e => setSignInEmail(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.875rem' }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                    Role Assignment
                  </label>
                  <select
                    value={signInRole}
                    onChange={e => setSignInRole(e.target.value as any)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--color-border)', fontSize: '0.875rem' }}
                  >
                    <option value="Analyst">Analyst (Ingest, review, correct)</option>
                    <option value="Reviewer">Reviewer (Auditing, approval)</option>
                    <option value="Admin">Admin (Schema packs, full access)</option>
                  </select>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setShowSignInModal(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                  >
                    Continue to Workspace
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <div style={{ position: 'relative' }} ref={menuRef}>
      {/* Avatar Button */}
      <button
        ref={buttonRef}
        className="avatar"
        style={{
          width: 36,
          height: 36,
          borderRadius: '50%',
          background: 'linear-gradient(135deg, var(--color-accent) 0%, #6366F1 100%)',
          color: '#ffffff',
          fontWeight: 700,
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '2px solid var(--color-surface)',
          boxShadow: 'var(--shadow-sm)',
          cursor: 'pointer',
          padding: 0,
        }}
        onClick={() => setIsOpen(v => !v)}
        aria-label={`Account menu for ${user?.name}`}
        aria-expanded={isOpen}
        aria-haspopup="true"
        id="user-account-menu-trigger"
      >
        {user?.avatarUrl ? (
          <img
            src={user.avatarUrl}
            alt={user.name}
            style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }}
          />
        ) : (
          initials
        )}
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div
          className="card"
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
            right: 0,
            width: 280,
            borderRadius: 12,
            boxShadow: 'var(--shadow-xl)',
            zIndex: 9999,
            padding: 0,
            overflow: 'hidden',
            border: '1px solid var(--color-border)',
            background: 'var(--color-surface)',
          }}
          role="menu"
          aria-orientation="vertical"
        >
          {/* Header Block: Avatar, Full Name, Email, Role */}
          <div style={{ padding: '14px 16px', background: 'var(--color-surface-2)', borderBottom: '1px solid var(--color-border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: '50%',
                  background: 'var(--color-accent)',
                  color: 'white',
                  fontWeight: 700,
                  fontSize: '0.875rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                {initials}
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--color-text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {user?.name}
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {user?.email}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
              <span className="badge badge-auto" style={{ fontSize: '0.7rem', padding: '2px 8px' }}>
                Role: {user?.role}
              </span>
              <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
                {user?.organization ? user.organization.split(' ')[0] : 'Acme'}
              </span>
            </div>
          </div>

          {/* Quick Theme Segmented Control: Light | Dark | System */}
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--color-border)' }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 6, textTransform: 'uppercase' }}>
              Theme Mode
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                background: 'var(--color-surface-2)',
                padding: 3,
                borderRadius: 8,
                border: '1px solid var(--color-border)',
                gap: 2,
              }}
            >
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setThemeMode('light')}
                style={{
                  padding: '4px 6px',
                  fontSize: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 4,
                  background: themeMode === 'light' ? 'var(--color-surface)' : 'transparent',
                  color: themeMode === 'light' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  boxShadow: themeMode === 'light' ? 'var(--shadow-sm)' : 'none',
                  border: 'none',
                  borderRadius: 6,
                  fontWeight: themeMode === 'light' ? 600 : 400,
                }}
              >
                <Sun size={13} /> Light
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setThemeMode('dark')}
                style={{
                  padding: '4px 6px',
                  fontSize: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 4,
                  background: themeMode === 'dark' ? 'var(--color-surface)' : 'transparent',
                  color: themeMode === 'dark' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  boxShadow: themeMode === 'dark' ? 'var(--shadow-sm)' : 'none',
                  border: 'none',
                  borderRadius: 6,
                  fontWeight: themeMode === 'dark' ? 600 : 400,
                }}
              >
                <Moon size={13} /> Dark
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setThemeMode('system')}
                style={{
                  padding: '4px 6px',
                  fontSize: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 4,
                  background: themeMode === 'system' ? 'var(--color-surface)' : 'transparent',
                  color: themeMode === 'system' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  boxShadow: themeMode === 'system' ? 'var(--shadow-sm)' : 'none',
                  border: 'none',
                  borderRadius: 6,
                  fontWeight: themeMode === 'system' ? 600 : 400,
                }}
              >
                <Laptop size={13} /> Auto
              </button>
            </div>
          </div>

          {/* Menu Items */}
          <div style={{ padding: '6px 0' }}>
            <button
              className="user-menu-item"
              onClick={() => {
                setIsOpen(false);
                navigate('/settings');
              }}
              style={{
                width: '100%',
                padding: '9px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                background: 'transparent',
                border: 'none',
                textAlign: 'left',
                fontSize: '0.85rem',
                color: 'var(--color-text-primary)',
                cursor: 'pointer',
              }}
            >
              <User size={15} color="var(--color-accent)" />
              <span>Profile & Settings</span>
            </button>

            <button
              className="user-menu-item"
              onClick={() => {
                setIsOpen(false);
                onOpenShortcuts?.();
              }}
              style={{
                width: '100%',
                padding: '9px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                background: 'transparent',
                border: 'none',
                textAlign: 'left',
                fontSize: '0.85rem',
                color: 'var(--color-text-primary)',
                cursor: 'pointer',
              }}
            >
              <Keyboard size={15} color="var(--color-text-muted)" />
              <span>Keyboard Shortcuts</span>
            </button>

            <button
              className="user-menu-item"
              onClick={() => {
                setIsOpen(false);
                navigate('/help');
              }}
              style={{
                width: '100%',
                padding: '9px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                background: 'transparent',
                border: 'none',
                textAlign: 'left',
                fontSize: '0.85rem',
                color: 'var(--color-text-primary)',
                cursor: 'pointer',
              }}
            >
              <HelpCircle size={15} color="var(--color-text-muted)" />
              <span>Help & Documentation</span>
            </button>
          </div>

          {/* Sign Out */}
          <div style={{ borderTop: '1px solid var(--color-border)', padding: '6px 0' }}>
            <button
              className="user-menu-item"
              onClick={() => {
                setIsOpen(false);
                signOut();
              }}
              style={{
                width: '100%',
                padding: '9px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                background: 'transparent',
                border: 'none',
                textAlign: 'left',
                fontSize: '0.85rem',
                color: 'var(--color-error)',
                cursor: 'pointer',
              }}
            >
              <LogOut size={15} />
              <span>Sign Out</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
