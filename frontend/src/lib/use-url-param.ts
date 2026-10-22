'use client';

import { useCallback, useEffect, useState } from 'react';

/**
 * A filter kept in the query string: read on load (so links like /disputes?status=pending
 * open filtered) and written back on change (so the url can be shared or reloaded).
 */
export function useUrlParam(name: string, fallback: string): [string, (value: string) => void] {
  const [value, setValue] = useState(fallback);

  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get(name);
    if (initial) setValue(initial);
  }, [name]);

  const update = useCallback(
    (next: string) => {
      setValue(next);
      const url = new URL(window.location.href);
      if (next && next !== fallback) url.searchParams.set(name, next);
      else url.searchParams.delete(name);
      window.history.replaceState(null, '', url);
    },
    [name, fallback],
  );

  return [value, update];
}
