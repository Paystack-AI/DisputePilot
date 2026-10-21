'use client';

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { format, parseISO } from 'date-fns';
import type { ReconciliationHealth } from '@/lib/types';

export function ReconciliationChart({ data }: { data: ReconciliationHealth | undefined }) {
  const series = (data?.series ?? []).map((item) => ({
    ...item,
    label: format(parseISO(item.date), 'd MMM'),
    matched_pct: item.matched_pct ?? 0,
  }));

  if (!series.length) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-ink-400">
        No reconciliation sessions yet
      </div>
    );
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={series} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="#e9edf2" />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#8298ad', fontSize: 11 }}
            minTickGap={28}
          />
          <YAxis
            domain={[0, 100]}
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#8298ad', fontSize: 11 }}
            tickFormatter={(value) => `${value}%`}
          />
          <Tooltip
            formatter={(value: number) => [`${value.toFixed(0)}%`, 'Match rate']}
            contentStyle={{
              borderRadius: 12,
              border: '1px solid #e4e7e1',
              boxShadow: '0 12px 32px -20px rgba(16, 24, 40, 0.3)',
              fontSize: 12,
            }}
          />
          <Bar dataKey="matched_pct" fill="#111c2b" radius={[5, 5, 0, 0]} maxBarSize={22} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
