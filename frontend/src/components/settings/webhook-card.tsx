'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Copy, RotateCw, Webhook } from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import { timeAgo } from '@/lib/format';
import type { WebhookSettings } from '@/lib/types';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Modal } from '@/components/ui/modal';

/** The merchant's own Paystack webhook URL, how to set it up, and rotating its token */
export function WebhookCard() {
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);

  const webhookQuery = useQuery({
    queryKey: ['settings', 'webhook'],
    queryFn: () => apiRequest<WebhookSettings>('/settings/webhook'),
    retry: false,
  });

  const rotateMutation = useMutation({
    mutationFn: () => apiRequest<WebhookSettings>('/settings/webhook/rotate', { method: 'POST' }),
    onSuccess: (webhook) => {
      queryClient.setQueryData(['settings', 'webhook'], webhook);
      setConfirmRotate(false);
      toast.success('New webhook URL created. Update it in Paystack now.');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const copy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error('Could not copy. Select the URL and copy it manually.');
    }
  };

  const webhook = webhookQuery.data;

  return (
    <Card>
      <CardHeader
        title="Paystack webhook"
        description="Real-time payments and disputes, instead of waiting for the next sync."
        action={<Webhook className="h-4 w-4 text-ink-400" />}
      />
      <CardBody className="space-y-4">
        {webhookQuery.isLoading ? (
          <div className="h-20 animate-pulse rounded-xl bg-ink-100" />
        ) : !webhook ? (
          <p className="text-[12px] leading-5 text-ink-500">
            Connect Paystack first to get your webhook URL.
          </p>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2">
              <Badge tone={webhook.active ? 'success' : 'warning'} dot>
                {webhook.active ? 'Receiving events' : 'Not set up yet'}
              </Badge>
              <span className="text-[11px] text-ink-400">
                {webhook.last_received_at
                  ? `Last event ${timeAgo(webhook.last_received_at)}`
                  : 'No events yet'}
              </span>
            </div>
            <div className="flex min-w-0 items-start gap-2 overflow-hidden rounded-xl bg-ink-50/70 p-2 ring-1 ring-inset ring-line">
              <code className="min-w-0 flex-1 select-all break-all px-1.5 font-mono text-[11px] leading-5 text-ink-700">
                {webhook.url}
              </code>
              <Button
                size="sm"
                variant="outline"
                className="shrink-0"
                onClick={() => copy(webhook.url)}
                aria-label="Copy webhook URL"
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            </div>
            {webhook.setup_steps.length ? (
              <ol className="list-decimal space-y-1.5 break-words pl-4 text-[11px] leading-5 text-ink-600 [overflow-wrap:anywhere]">
                {webhook.setup_steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            ) : null}
            {webhook.events.length ? (
              <div className="flex flex-wrap gap-1.5">
                {webhook.events.map((event) => (
                  <Badge key={event} tone="neutral" className="font-mono">
                    {event}
                  </Badge>
                ))}
              </div>
            ) : null}
            <Button variant="ghost" size="sm" onClick={() => setConfirmRotate(true)}>
              <RotateCw className="h-3.5 w-3.5" /> Rotate URL
            </Button>
          </>
        )}
      </CardBody>

      <Modal
        open={confirmRotate}
        onClose={() => setConfirmRotate(false)}
        title="Rotate the webhook URL?"
        description="The current URL stops working immediately. Paste the new one into Paystack straight away, or events are missed until the next sync."
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmRotate(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => rotateMutation.mutate()}
              loading={rotateMutation.isPending}
            >
              Rotate
            </Button>
          </>
        }
      >
        <p className="text-[13px] leading-6 text-ink-600">
          Only rotate if you think the URL has leaked.
        </p>
      </Modal>
    </Card>
  );
}
