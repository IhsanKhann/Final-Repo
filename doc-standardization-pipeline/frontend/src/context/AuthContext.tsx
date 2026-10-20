import React, { createContext, useContext, useState, useCallback } from 'react';

export type UserRole = 'Analyst' | 'Reviewer' | 'Admin';

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  jobTitle: string;
  organization: string;
  avatarUrl?: string;
  timezone: string;
  language: string;
  dateFormat: string;
}

const DEFAULT_USER: UserProfile = {
  id: 'usr-001',
  name: 'Amina Khan',
  email: 'amina.khan@acmemining.com',
  role: 'Analyst',
  jobTitle: 'Senior ESG & Operational Analyst',
  organization: 'Acme Mining & Metals Global',
  avatarUrl: '',
  timezone: 'Asia/Karachi',
  language: 'English (US)',
  dateFormat: 'YYYY-MM-DD',
};

interface AuthContextValue {
  user: UserProfile | null;
  isAuthenticated: boolean;
  signIn: (email: string, role?: UserRole, name?: string) => void;
  signOut: () => void;
  updateProfile: (updates: Partial<UserProfile>) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(DEFAULT_USER);

  const signIn = useCallback((email: string, role: UserRole = 'Analyst', name?: string) => {
    setUser({
      ...DEFAULT_USER,
      id: `usr-${Date.now()}`,
      email,
      role,
      name: name || (email.split('@')[0].replace(/[._]/g, ' ').replace(/\b\w/g, l => l.toUpperCase())),
    });
  }, []);

  const signOut = useCallback(() => {
    setUser(null);
  }, []);

  const updateProfile = useCallback((updates: Partial<UserProfile>) => {
    setUser(prev => prev ? { ...prev, ...updates } : null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        signIn,
        signOut,
        updateProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
