'use client';

import { useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { createQueryClient } from '@/lib/query-client';

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster
        position="top-right"
        toastOptions={{
          className: 'rounded-xl border border-line text-sm',
        }}
      />
    </QueryClientProvider>
  );
}
