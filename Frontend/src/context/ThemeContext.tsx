import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';
export type Density = 'comfortable' | 'compact';
export type TextSize = 'default' | 'large' | 'extra-large';
export type ReduceMotion = 'system' | 'on' | 'off';

interface ThemeContextValue {
  themeMode: ThemeMode;
  resolvedTheme: 'light' | 'dark';
  setThemeMode: (mode: ThemeMode) => void;
  density: Density;
  setDensity: (d: Density) => void;
  textSize: TextSize;
  setTextSize: (s: TextSize) => void;
  reduceMotion: ReduceMotion;
  setReduceMotion: (r: ReduceMotion) => void;
  dimDocuments: boolean;
  setDimDocuments: (dim: boolean) => void;
  highContrast: boolean;
  setHighContrast: (hc: boolean) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [themeMode, setThemeModeState] = useState<ThemeMode>(() => {
    return (localStorage.getItem('theme') as ThemeMode) || 'system';
  });

  const [density, setDensityState] = useState<Density>(() => {
    return (localStorage.getItem('density') as Density) || 'comfortable';
  });

  const [textSize, setTextSizeState] = useState<TextSize>(() => {
    return (localStorage.getItem('textSize') as TextSize) || 'default';
  });

  const [reduceMotion, setReduceMotionState] = useState<ReduceMotion>(() => {
    return (localStorage.getItem('reduceMotion') as ReduceMotion) || 'system';
  });

  const [dimDocuments, setDimDocumentsState] = useState<boolean>(() => {
    return localStorage.getItem('dimDocuments') === 'true';
  });

  const [highContrast, setHighContrastState] = useState<boolean>(() => {
    return localStorage.getItem('contrast') === 'high';
  });

  const [systemIsDark, setSystemIsDark] = useState<boolean>(() => {
    return typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  // Listen to OS dark mode changes
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setSystemIsDark(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  const resolvedTheme: 'light' | 'dark' = themeMode === 'system' ? (systemIsDark ? 'dark' : 'light') : themeMode;

  // Apply attributes to <html>
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-theme', resolvedTheme);
    root.style.colorScheme = resolvedTheme;
  }, [resolvedTheme]);

  useEffect(() => {
    const root = document.documentElement;
    if (density === 'compact') {
      root.setAttribute('data-density', 'compact');
    } else {
      root.removeAttribute('data-density');
    }
  }, [density]);

  useEffect(() => {
    const root = document.documentElement;
    if (textSize !== 'default') {
      root.setAttribute('data-text-size', textSize);
    } else {
      root.removeAttribute('data-text-size');
    }
  }, [textSize]);

  useEffect(() => {
    const root = document.documentElement;
    if (reduceMotion === 'on') {
      root.setAttribute('data-reduce-motion', 'on');
    } else if (reduceMotion === 'off') {
      root.setAttribute('data-reduce-motion', 'off');
    } else {
      root.removeAttribute('data-reduce-motion');
    }
  }, [reduceMotion]);

  useEffect(() => {
    const root = document.documentElement;
    if (dimDocuments) {
      root.setAttribute('data-dim-documents', 'true');
    } else {
      root.removeAttribute('data-dim-documents');
    }
  }, [dimDocuments]);

  useEffect(() => {
    const root = document.documentElement;
    if (highContrast) {
      root.setAttribute('data-contrast', 'high');
    } else {
      root.removeAttribute('data-contrast');
    }
  }, [highContrast]);

  const setThemeMode = useCallback((mode: ThemeMode) => {
    setThemeModeState(mode);
    localStorage.setItem('theme', mode);
  }, []);

  const setDensity = useCallback((d: Density) => {
    setDensityState(d);
    localStorage.setItem('density', d);
  }, []);

  const setTextSize = useCallback((s: TextSize) => {
    setTextSizeState(s);
    localStorage.setItem('textSize', s);
  }, []);

  const setReduceMotion = useCallback((r: ReduceMotion) => {
    setReduceMotionState(r);
    localStorage.setItem('reduceMotion', r);
  }, []);

  const setDimDocuments = useCallback((dim: boolean) => {
    setDimDocumentsState(dim);
    localStorage.setItem('dimDocuments', String(dim));
  }, []);

  const setHighContrast = useCallback((hc: boolean) => {
    setHighContrastState(hc);
    localStorage.setItem('contrast', hc ? 'high' : 'normal');
  }, []);

  return (
    <ThemeContext.Provider
      value={{
        themeMode,
        resolvedTheme,
        setThemeMode,
        density,
        setDensity,
        textSize,
        setTextSize,
        reduceMotion,
        setReduceMotion,
        dimDocuments,
        setDimDocuments,
        highContrast,
        setHighContrast,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
