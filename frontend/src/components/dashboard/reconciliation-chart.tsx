'use client';

import { useChartColors } from '@/lib/chart-colors';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { format, parseISO } from 'date-fns';
import type { ReconciliationHealth } from '@/lib/types';

export function ReconciliationChart({ data }: { data: ReconciliationHealth | undefined }) {
  const c = useChartColors();
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
          <CartesianGrid vertical={false} stroke={c.grid} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tick={{ fill: c.axis, fontSize: 11 }}
            minTickGap={28}
          />
          <YAxis
            domain={[0, 100]}
            tickLine={false}
            axisLine={false}
            tick={{ fill: c.axis, fontSize: 11 }}
            tickFormatter={(value) => `${value}%`}
          />
          <Tooltip
            formatter={(value: number) => [`${value.toFixed(0)}%`, 'Match rate']}
            contentStyle={{
              borderRadius: 8,
              border: `1px solid ${c.grid}`,
              background: c.surface,
              color: c.text,
              boxShadow: 'none',
              fontSize: 12,
            }}
          />
          <Bar dataKey="matched_pct" fill={c.primary} radius={[3, 3, 0, 0]} maxBarSize={22} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
