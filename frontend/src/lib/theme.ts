'use client';

import { useEffect, useState } from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'disputepilot.theme';
// every useTheme instance (toggle, toaster) listens for this, so they stay in step
const CHANGE_EVENT = 'disputepilot:theme';

/**
 * Runs in <head> before the page paints, so a dark-mode user never sees a white flash.
 * Kept as a string because it is inlined into the html.
 */
export const themeBootScript = `(function(){try{var c=localStorage.getItem('${STORAGE_KEY}');var d=c==='dark'||((!c||c==='system')&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);}catch(e){}})();`;

function readChoice(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    return 'system';
  }
}

function systemDark() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function apply(choice: ThemeChoice) {
  const dark = choice === 'dark' || (choice === 'system' && systemDark());
  document.documentElement.classList.toggle('dark', dark);
  return dark;
}

/** The saved choice, whether dark is showing, and a setter that persists it */
export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>('system');
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const saved = readChoice();
    setChoice(saved);
    setDark(apply(saved));

    // following the system: change along with it
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const onSystem = () => {
      if (readChoice() === 'system') setDark(apply('system'));
    };
    const onChange = () => {
      const next = readChoice();
      setChoice(next);
      setDark(apply(next));
    };
    media.addEventListener('change', onSystem);
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => {
      media.removeEventListener('change', onSystem);
      window.removeEventListener(CHANGE_EVENT, onChange);
    };
  }, []);

  const set = (next: ThemeChoice) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // private mode: the choice lasts for this page only
    }
    setChoice(next);
    setDark(apply(next));
    window.dispatchEvent(new Event(CHANGE_EVENT));
  };

  return { choice, dark, set, toggle: () => set(dark ? 'light' : 'dark') };
}
