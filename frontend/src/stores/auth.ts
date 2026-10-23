'use client';

import { create } from 'zustand';
import { clearSession, getSession, setSession } from '@/lib/auth-storage';
type AuthState = {
  session: boolean;
  setSession: () => void;
  clear: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  session: getSession(),
  setSession: () => {
    setSession();
    set({ session: true });
  },
  clear: () => {
    clearSession();
    set({ session: false });
  },
}));
