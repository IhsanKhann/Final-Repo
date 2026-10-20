import React, { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Home, Upload, LayoutList, Eye, Database,
  Settings, BarChart2, HelpCircle, ChevronLeft,
  ChevronRight, Search, Layers, Menu,
} from 'lucide-react';
import { getHealth, getPacks } from '../../api/client';
import { useActivePack } from '../../context/AppContext';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

interface NavItemDef {
  to: string;
  label: string;
  icon: React.ReactNode;
  badge?: number;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const { activePack, setActivePack } = useActivePack();

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30000,
  });

  const { data: packs } = useQuery({
    queryKey: ['packs'],
    queryFn: getPacks,
  });

  const navigate = useNavigate();

  const mainNav: NavItemDef[] = [
    { to: '/', label: 'Home', icon: <Home size={18} /> },
    { to: '/upload', label: 'Upload', icon: <Upload size={18} /> },
    { to: '/batches', label: 'Batches', icon: <LayoutList size={18} /> },
    { to: '/review', label: 'Review', icon: <Eye size={18} />, badge: 11 },
    { to: '/dataset', label: 'Dataset', icon: <Database size={18} /> },
  ];

  const toolsNav: NavItemDef[] = [
    { to: '/schema', label: 'Schema & Rules', icon: <Layers size={18} /> },
    { to: '/insights', label: 'Insights', icon: <BarChart2 size={18} /> },
  ];

  const bottomNav: NavItemDef[] = [
    { to: '/help', label: 'Help', icon: <HelpCircle size={18} /> },
    { to: '/settings', label: 'Settings', icon: <Settings size={18} /> },
  ];

  const overallStatus = health?.overall ?? 'ok';

  return (
    <div className="app-shell">
      {USE_MOCK && (
        <div className="mock-banner" role="banner" aria-label="Mock data mode active">
          ⚠ MOCK DATA — Development Only — Not Real Results
        </div>
      )}

      {/* Sidebar */}
      <nav
        className={`sidebar${sidebarCollapsed ? ' collapsed' : ''}`}
        aria-label="Main navigation"
      >
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <div className="sidebar-logo-text">
            <span className="sidebar-logo-title">DataSync</span>
            <span className="sidebar-logo-sub">Standardization Agent</span>
          </div>
        </div>

        <div className="sidebar-nav">
          <span className="sidebar-section-label">Workspace</span>
          {mainNav.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              aria-label={sidebarCollapsed ? item.label : undefined}
            >
              <span className="nav-item-icon">{item.icon}</span>
              <span className="nav-item-label">{item.label}</span>
              {item.badge != null && item.badge > 0 && (
                <span className="nav-badge" aria-label={`${item.badge} items need review`}>
                  {item.badge}
                </span>
              )}
            </NavLink>
          ))}

          <span className="sidebar-section-label">Configure</span>
          {toolsNav.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              aria-label={sidebarCollapsed ? item.label : undefined}
            >
              <span className="nav-item-icon">{item.icon}</span>
              <span className="nav-item-label">{item.label}</span>
            </NavLink>
          ))}
        </div>

        <div className="sidebar-footer">
          {bottomNav.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              aria-label={sidebarCollapsed ? item.label : undefined}
            >
              <span className="nav-item-icon">{item.icon}</span>
              <span className="nav-item-label">{item.label}</span>
            </NavLink>
          ))}
          <button
            className="nav-item"
            onClick={() => setSidebarCollapsed(v => !v)}
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <span className="nav-item-icon">
              {sidebarCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
            </span>
            <span className="nav-item-label">Collapse</span>
          </button>
        </div>
      </nav>

      {/* Main */}
      <div className="app-main">
        <header className="app-header" role="banner">
          {/* Schema Pack Selector */}
          <div className="header-pack-selector">
            <Layers size={16} color="var(--color-text-muted)" aria-hidden="true" />
            <div className="select-wrapper">
              <select
                id="schema-pack-selector"
                value={activePack}
                onChange={e => setActivePack(e.target.value)}
                aria-label="Active schema pack"
                style={{ fontSize: '0.8125rem', padding: '5px 28px 5px 10px', minWidth: 140 }}
              >
                {(packs ?? []).map(p => (
                  <option key={p.id} value={p.id}>{p.name} {p.version}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Search */}
          <div className="header-search" role="search">
            <Search size={14} className="header-search-icon" aria-hidden="true" />
            <input
              type="search"
              placeholder="Search fields, documents… (/)"
              aria-label="Search"
              id="header-search"
              onKeyDown={e => {
                if (e.key === '/') { e.preventDefault(); (e.target as HTMLInputElement).focus(); }
              }}
            />
          </div>

          {/* Actions */}
          <div className="header-actions">
            {/* System Status Chip */}
            <button
              className={`status-chip ${overallStatus}`}
              onClick={() => navigate('/health')}
              aria-label={`System status: ${overallStatus}. Click to view details.`}
              id="system-status-chip"
            >
              <span className="status-dot" aria-hidden="true" />
              {overallStatus === 'ok' ? 'All systems OK' :
               overallStatus === 'degraded' ? 'Degraded' : 'System down'}
            </button>

            {/* Avatar */}
            <div className="avatar" role="img" aria-label="User account" tabIndex={0}>
              A
            </div>
          </div>
        </header>

        {/* Page */}
        <main id="main-content" className="page-content" tabIndex={-1}>
          {children}
        </main>

        {/* Mobile Bottom Tab Bar */}
        <nav className="bottom-tab-bar" aria-label="Mobile navigation">
          {[
            { to: '/', icon: <Home size={20} />, label: 'Home' },
            { to: '/upload', icon: <Upload size={20} />, label: 'Upload' },
            { to: '/review', icon: <Eye size={20} />, label: 'Review' },
            { to: '/dataset', icon: <Database size={20} />, label: 'Data' },
            { to: '/schema', icon: <Menu size={20} />, label: 'More' },
          ].map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `bottom-tab-item${isActive ? ' active' : ''}`}
            >
              {item.icon}
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
