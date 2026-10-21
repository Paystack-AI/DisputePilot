'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Rocket } from 'lucide-react';
import { apiRequest } from '@/lib/api';
import { useLiveEvents } from '@/hooks/use-live-events';
import type { Merchant, Onboarding } from '@/lib/types';
import { Protected } from './protected';
import { Sidebar } from './sidebar';
import { Topbar } from './topbar';

function OnboardingBanner() {
  const pathname = usePathname();
  const { data: merchant } = useQuery({
    queryKey: ['merchant', 'me'],
    queryFn: () => apiRequest<Merchant>('/auth/me'),
    staleTime: 5 * 60_000,
  });
  const { data: onboarding } = useQuery({
    queryKey: ['onboarding'],
    queryFn: () => apiRequest<Onboarding>('/onboarding'),
    staleTime: 30_000,
  });

  if (!merchant || !onboarding || onboarding.completed || pathname === '/onboarding') return null;

  return (
    <div className="mx-4 mt-4 flex flex-col items-start justify-between gap-3 rounded-2xl border border-brand-200 bg-brand-50 px-4 py-3.5 sm:mx-6 sm:flex-row sm:items-center lg:mx-8">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-500 text-white">
          <Rocket className="h-4 w-4" />
        </div>
        <div>
          <p className="text-[13px] font-semibold text-brand-900">
            Finish setting up your workspace
          </p>
          <p className="mt-0.5 text-[12px] leading-5 text-brand-800">
            Connect Paystack, choose notifications and sync your first transactions.
          </p>
        </div>
      </div>
      <Link
        href="/onboarding"
        className="inline-flex items-center gap-1.5 rounded-lg bg-brand-700 px-3 py-2 text-[12px] font-semibold text-white transition hover:bg-brand-800"
      >
        Continue setup <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

function LiveEvents() {
  useLiveEvents();
  return null;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { data: merchant } = useQuery({
    queryKey: ['merchant', 'me'],
    queryFn: () => apiRequest<Merchant>('/auth/me'),
    staleTime: 5 * 60_000,
  });

  return (
    <Protected>
      <LiveEvents />
      <div className="min-h-screen bg-canvas">
        <Sidebar
          businessName={merchant?.business_name}
          mobileOpen={mobileOpen}
          onClose={() => setMobileOpen(false)}
        />
        <div className="lg:pl-64">
          <Topbar onMenu={() => setMobileOpen(true)} />
          <OnboardingBanner />
          <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            {children}
          </main>
        </div>
      </div>
    </Protected>
  );
}
