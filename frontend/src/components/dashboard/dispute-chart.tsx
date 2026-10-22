'use client';

import { useChartColors } from '@/lib/chart-colors';
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
  const c = useChartColors();
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
              <stop offset="0%" stopColor={c.primary} stopOpacity={0.28} />
              <stop offset="100%" stopColor={c.primary} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="wonFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={c.success} stopOpacity={0.16} />
              <stop offset="100%" stopColor={c.success} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={c.grid} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tick={{ fill: c.axis, fontSize: 11 }}
            minTickGap={28}
          />
          <YAxis
            allowDecimals={false}
            tickLine={false}
            axisLine={false}
            tick={{ fill: c.axis, fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 8,
              border: `1px solid ${c.grid}`,
              background: c.surface,
              color: c.text,
              boxShadow: 'none',
              fontSize: 12,
            }}
          />
          <Area
            type="monotone"
            dataKey="opened"
            name="Opened"
            stroke={c.primary}
            strokeWidth={2}
            fill="url(#openedFill)"
          />
          <Area
            type="monotone"
            dataKey="won"
            name="Won"
            stroke={c.success}
            strokeWidth={1.5}
            fill="url(#wonFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
