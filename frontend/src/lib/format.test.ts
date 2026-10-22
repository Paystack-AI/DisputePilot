import { describe, expect, it } from 'vitest';
import {
  deadlineLabel,
  formatMoney,
  formatNumber,
  percent,
  queryString,
  titleCase,
} from './format';

describe('format helpers', () => {
  it('formats minor units as currency', () => {
    expect(formatMoney(150000, 'NGN')).toContain('1,500');
    expect(formatMoney(null)).toBe('—');
  });

  it('formats counts and percentages', () => {
    expect(formatNumber(1234567)).toBe('1,234,567');
    expect(percent(12.345, 1)).toBe('12.3%');
    expect(percent(null)).toBe('—');
  });

  it('builds query strings without empty values', () => {
    expect(queryString({ page: 2, search: 'ada', empty: '', missing: null })).toBe(
      '?page=2&search=ada',
    );
    expect(queryString({})).toBe('');
  });

  it('labels deadlines from server time', () => {
    expect(deadlineLabel('2026-01-03T03:00:00Z', '2026-01-01T00:00:00Z')).toBe('2d 3h');
    expect(deadlineLabel('2026-01-01T05:30:00Z', '2026-01-01T00:00:00Z')).toBe('5h 30m');
  });

  it('turns snake case into a title', () => {
    expect(titleCase('chargeback_no_value')).toBe('Chargeback No Value');
  });
});
