'use client';

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import type { DisputeTimeline } from '@/lib/types';

export function DisputeChart({ data }: { data: DisputeTimeline | undefined }) {
  const series = (data?.series ?? []).map((item) => ({
    ...item,
    label: format(parseISO(item.date), 'd MMM'),
  }));

  if (!series.length) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-ink-400">
        No dispute activity yet
      </div>
    );
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={series} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
          <defs>
            <linearGradient id="openedFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#20a46c" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#20a46c" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="wonFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#45c087" stopOpacity={0.16} />
              <stop offset="100%" stopColor="#45c087" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="#e9edf2" />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#8298ad', fontSize: 11 }}
            minTickGap={28}
          />
          <YAxis
            allowDecimals={false}
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#8298ad', fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 12,
              border: '1px solid #e4e7e1',
              boxShadow: '0 12px 32px -20px rgba(16, 24, 40, 0.3)',
              fontSize: 12,
            }}
          />
          <Area
            type="monotone"
            dataKey="opened"
            name="Opened"
            stroke="#20a46c"
            strokeWidth={2}
            fill="url(#openedFill)"
          />
          <Area
            type="monotone"
            dataKey="won"
            name="Won"
            stroke="#7bd9ab"
            strokeWidth={1.5}
            fill="url(#wonFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
