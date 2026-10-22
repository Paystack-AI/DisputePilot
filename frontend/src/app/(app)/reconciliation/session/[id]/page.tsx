'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { apiRequest } from '@/lib/api';
import type { ReconciliationView } from '@/lib/types';
import { PageHeader } from '@/components/ui/page-header';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { ReconciliationSessionView } from '@/components/reconciliation/session-view';

export default function SessionDetailPage() {
  const params = useParams<{ id: string }>();
  const { data, isLoading, error } = useQuery({
    queryKey: ['reconciliation', 'session', params.id],
    queryFn: () => apiRequest<ReconciliationView>(`/reconciliation/sessions/${params.id}`),
    enabled: Boolean(params.id),
  });

  if (isLoading) return <PageSkeleton />;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Reconciliation history"
        title="Session detail"
        description="A read-only record of the matching decisions made for this period."
        actions={
          <Link href="/reconciliation">
            <Button variant="outline">
              <ArrowLeft className="h-4 w-4" /> Back to workspace
            </Button>
          </Link>
        }
      />
      {error ? (
        <Alert tone="danger" title="Could not load this session">
          {error instanceof Error ? error.message : 'Please try again.'}
        </Alert>
      ) : data ? (
        <ReconciliationSessionView view={data} readOnly />
      ) : null}
    </div>
  );
}
