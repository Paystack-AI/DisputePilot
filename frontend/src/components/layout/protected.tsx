'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/auth';
import { Brand } from '@/components/brand';

export function Protected({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const session = useAuthStore((state) => state.session);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!session) {
      const next = pathname && pathname !== '/' ? `?next=${encodeURIComponent(pathname)}` : '';
      router.replace(`/login${next}`);
      return;
    }
    setChecked(true);
  }, [pathname, router, session]);

  if (!checked || !session) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-canvas">
        <Brand />
        <div className="flex items-center gap-2 text-sm text-ink-500">
          <span className="h-2 w-2 animate-pulse rounded-full bg-brand-500" />
          Opening your workspace
        </div>
      </div>
    );
  }

  return children;
}
