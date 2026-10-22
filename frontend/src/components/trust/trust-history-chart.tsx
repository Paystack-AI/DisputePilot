'use client';

import { useChartColors } from '@/lib/chart-colors';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import type { TrustHistory } from '@/lib/types';

export function TrustHistoryChart({ history }: { history: TrustHistory | undefined }) {
  const c = useChartColors();
  const points = (history?.points ?? []).map((point) => ({
    ...point,
    label: format(parseISO(point.at), 'd MMM'),
    score: point.internal_score ?? 0,
  }));

  if (!points.length) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-ink-400">
        Trust history appears after the first computation
      </div>
    );
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
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
            formatter={(value: number) => [value, 'Trust score']}
          />
          <Line
            type="monotone"
            dataKey="score"
            stroke={c.primary}
            strokeWidth={2.5}
            dot={{ r: 3, fill: c.primary, strokeWidth: 0 }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
