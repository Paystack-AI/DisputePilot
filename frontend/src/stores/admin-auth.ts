'use client';

import { create } from 'zustand';
import {
  clearAdminToken,
  getAdminToken,
  setAdminToken as persistAdminToken,
} from '@/lib/auth-storage';

type AdminAuthState = {
  token: boolean;
  setToken: () => void;
  clear: () => void;
};

export const useAdminAuthStore = create<AdminAuthState>((set) => ({
  token: getAdminToken(),
  setToken: () => {
    persistAdminToken();
    set({ token: true });
  },
  clear: () => {
    clearAdminToken();
    set({ token: false });
  },
}));
