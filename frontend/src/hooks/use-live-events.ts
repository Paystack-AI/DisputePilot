'use client';

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { refreshMerchantSession } from '@/lib/api';
import { getSession } from '@/lib/auth-storage';

// the query keys each server event makes stale
const INVALIDATES: Record<string, string[][]> = {
  'dispute.created': [['disputes'], ['dashboard'], ['customer']],
  'dispute.updated': [['disputes'], ['dispute'], ['dashboard']],
  'deadline.warning': [['disputes'], ['dashboard']],
  'transaction.synced': [['transactions'], ['reconciliation'], ['dashboard'], ['onboarding']],
  'reconciliation.updated': [['reconciliation'], ['transactions'], ['orders'], ['dashboard']],
  'trust.updated': [['trust'], ['dashboard']],
};

const TOASTS: Record<string, string> = {
  'dispute.created': 'A new dispute just arrived',
  'deadline.warning': 'A dispute deadline is close',
  'reconciliation.updated': 'Reconciliation finished',
};

const RETRY_MS = 5_000;

type ServerEvent = { id: string | null; event: string; data: string };

/** Splits an event-stream body into events; returns what is left of an unfinished one */
function parse(buffer: string, onEvent: (event: ServerEvent) => void): string {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? '';
  for (const block of blocks) {
    const event: ServerEvent = { id: null, event: 'message', data: '' };
    for (const line of block.split(/\r?\n/)) {
      if (!line || line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon === -1 ? line : line.slice(0, colon);
      const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '');
      if (field === 'event') event.event = value;
      else if (field === 'data') event.data += event.data ? `\n${value}` : value;
      else if (field === 'id') event.id = value;
    }
    if (event.event !== 'message' || event.data) onEvent(event);
  }
  return rest;
}

/**
 * Keeps one live connection to GET /events while the merchant is signed in, and refreshes
 * the screens an event touches. A fetch stream rather than EventSource so the bearer token
 * goes in the Authorization header, the same way every other call is authenticated.
 */
export function useLiveEvents() {
  const queryClient = useQueryClient();

  useEffect(() => {
    let stopped = false;
    let lastEventId: string | null = null;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const handle = (event: ServerEvent) => {
      if (event.id) lastEventId = event.id;
      if (event.event === 'resync') {
        queryClient.invalidateQueries();
        return;
      }
      INVALIDATES[event.event]?.forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
      const message = TOASTS[event.event];
      if (message) toast.info(message);
    };

    const connect = async () => {
      if (stopped) return;
      const token = getSession()?.access_token;
      if (!token) return;

      controller = new AbortController();
      let expired = false;
      try {
        const headers: Record<string, string> = {
          Accept: 'text/event-stream',
          Authorization: `Bearer ${token}`,
        };
        if (lastEventId) headers['Last-Event-ID'] = lastEventId;
        const response = await fetch('/api/proxy/events', { headers, signal: controller.signal });

        if (response.status === 401) {
          expired = true;
        } else if (response.ok && response.body) {
          const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
          let buffer = '';
          while (!stopped) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer = parse(buffer + value, (event) => {
              if (event.event === 'session_expired') expired = true;
              else handle(event);
            });
          }
        }
      } catch {
        // network drop or abort: retried below unless stopped
      }

      if (stopped) return;
      if (expired) {
        // a failed refresh signs out through the next api call; stop here
        if (!(await refreshMerchantSession())) return;
        connect();
        return;
      }
      timer = setTimeout(connect, RETRY_MS);
    };

    connect();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [queryClient]);
}
