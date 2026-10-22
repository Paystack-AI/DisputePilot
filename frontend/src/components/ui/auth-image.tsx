'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ImageOff } from 'lucide-react';
import { apiBlob } from '@/lib/api';
import { cn } from '@/lib/cn';

export function AuthImage({
  fileId,
  alt,
  className,
  onClick,
}: {
  fileId: string;
  alt: string;
  className?: string;
  onClick?: () => void;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ['upload', fileId],
    queryFn: () => apiBlob(`/uploads/${fileId}`),
    staleTime: Infinity,
    retry: false,
  });

  useEffect(() => {
    if (!data) return;
    const url = URL.createObjectURL(data);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [data]);

  if (isLoading) return <div className={cn('animate-pulse rounded-xl bg-ink-100', className)} />;
  if (isError || !src) {
    return (
      <div
        className={cn(
          'flex items-center justify-center rounded-xl bg-ink-100 text-ink-400',
          className,
        )}
      >
        <ImageOff className="h-5 w-5" />
      </div>
    );
  }

  return (
    <button type="button" onClick={onClick} className={cn('block overflow-hidden', className)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} className="h-full w-full object-cover" />
    </button>
  );
}
