'use client';

import { create } from 'zustand';
import { clearSession, getSession, setSession } from '@/lib/auth-storage';
import type { Token } from '@/lib/types';

type AuthState = {
  session: Token | null;
  setSession: (token: Token) => void;
  clear: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  session: getSession(),
  setSession: (token) => {
    setSession(token);
    set({ session: token });
  },
  clear: () => {
    clearSession();
    set({ session: null });
  },
}));
