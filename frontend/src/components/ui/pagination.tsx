'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { PageMeta } from '@/lib/types';
import { Button } from './button';

export function Pagination({
  meta,
  onPageChange,
}: {
  meta: PageMeta | undefined;
  onPageChange: (page: number) => void;
}) {
  if (!meta || meta.total_pages <= 1) return null;

  return (
    <div className="flex flex-col items-center justify-between gap-3 border-t border-line px-5 py-4 sm:flex-row">
      <p className="text-[12px] text-ink-500">
        Showing {(meta.page - 1) * meta.limit + 1}–{Math.min(meta.page * meta.limit, meta.total)} of{' '}
        {meta.total}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(meta.page - 1)}
          disabled={meta.page <= 1}
        >
          <ChevronLeft className="h-4 w-4" />
          Previous
        </Button>
        <span className="px-2 text-[12px] font-semibold text-ink-600">
          {meta.page} / {meta.total_pages}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(meta.page + 1)}
          disabled={meta.page >= meta.total_pages}
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
