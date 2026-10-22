'use client';

import { useEffect, useState } from 'react';
import { useTheme } from './theme';

const NAMES = {
  grid: '--line',
  axis: '--ink-400',
  text: '--ink-700',
  primary: '--brand-500',
  primarySoft: '--brand-100',
  success: '--emerald-500',
  danger: '--red-500',
  warning: '--amber-500',
  surface: '--surface',
} as const;

type ChartColors = Record<keyof typeof NAMES, string>;

const LIGHT: ChartColors = {
  grid: 'rgb(228 232 238)',
  axis: 'rgb(148 160 178)',
  text: 'rgb(51 65 85)',
  primary: 'rgb(59 110 246)',
  primarySoft: 'rgb(219 231 254)',
  success: 'rgb(16 185 129)',
  danger: 'rgb(239 68 68)',
  warning: 'rgb(245 158 11)',
  surface: 'rgb(255 255 255)',
};

/**
 * The theme's colours as plain rgb() strings. Recharts writes colours into svg attributes,
 * where css variables are not reliable, so they are read here and refreshed on theme change.
 */
export function useChartColors(): ChartColors {
  const { dark } = useTheme();
  const [colors, setColors] = useState<ChartColors>(LIGHT);

  useEffect(() => {
    const style = getComputedStyle(document.documentElement);
    const next = { ...LIGHT };
    (Object.keys(NAMES) as (keyof typeof NAMES)[]).forEach((key) => {
      const value = style.getPropertyValue(NAMES[key]).trim();
      if (value) next[key] = `rgb(${value})`;
    });
    setColors(next);
  }, [dark]);

  return colors;
}
