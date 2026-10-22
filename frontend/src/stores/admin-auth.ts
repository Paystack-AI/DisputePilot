'use client';

import { create } from 'zustand';
import {
  clearAdminToken,
  getAdminToken,
  setAdminToken as persistAdminToken,
} from '@/lib/auth-storage';

type AdminAuthState = {
  token: string | null;
  setToken: (token: string) => void;
  clear: () => void;
};

export const useAdminAuthStore = create<AdminAuthState>((set) => ({
  token: getAdminToken(),
  setToken: (token) => {
    persistAdminToken({ access_token: token });
    set({ token });
  },
  clear: () => {
    clearAdminToken();
    set({ token: null });
  },
}));
