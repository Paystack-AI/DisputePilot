'use client';

import { useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { createQueryClient } from '@/lib/query-client';
import { useTheme } from '@/lib/theme';

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(createQueryClient);
  const { dark } = useTheme();

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster
        position="top-right"
        theme={dark ? 'dark' : 'light'}
        toastOptions={{
          className: 'rounded-lg border border-line text-sm',
        }}
      />
    </QueryClientProvider>
  );
}
