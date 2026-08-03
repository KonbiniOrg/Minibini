import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  formatQtyUnits, parseDurationToISO, formatDuration, formatSessionDateTime,
  parseDurationToHours, durationToHours, formatMoney,
} from '@/lib/format.js';

describe('formatMoney', () => {
  it('puts the minus sign before the dollar sign, not "$-"', () => {
    expect(formatMoney(-80)).toBe('-$80.00');
  });

  it('formats a positive amount normally', () => {
    expect(formatMoney(80)).toBe('$80.00');
  });

  it('formats zero', () => {
    expect(formatMoney(0)).toBe('$0.00');
  });

  it('accepts a string number (as line-item/fee amounts arrive from the API)', () => {
    expect(formatMoney('80.00')).toBe('$80.00');
    expect(formatMoney('-80.00')).toBe('-$80.00');
  });

  it('supports a whole-dollar (0 decimals) mode without mangling a negative', () => {
    expect(formatMoney(-12400, { decimals: 0 })).toBe('-$12,400');
    expect(formatMoney(12400, { decimals: 0 })).toBe('$12,400');
  });
});

describe('formatQtyUnits', () => {
  it('returns a dash for null/undefined/empty quantity', () => {
    expect(formatQtyUnits(null)).toBe('-');
    expect(formatQtyUnits(undefined)).toBe('-');
    expect(formatQtyUnits('')).toBe('-');
  });

  it('omits units when units are missing or "none"', () => {
    expect(formatQtyUnits(5, null)).toBe('5');
    expect(formatQtyUnits(5, 'none')).toBe('5');
  });

  it('appends real units, and keeps a zero quantity', () => {
    expect(formatQtyUnits(5, 'kg')).toBe('5 kg');
    expect(formatQtyUnits(0, 'kg')).toBe('0 kg');
  });
});

describe('parseDurationToISO', () => {
  it('returns null for empty input', () => {
    expect(parseDurationToISO('')).toBeNull();
    expect(parseDurationToISO(null)).toBeNull();
    expect(parseDurationToISO('   ')).toBeNull();
  });

  it('parses HH:MM', () => {
    expect(parseDurationToISO('1:30')).toBe('PT1H30M');
    expect(parseDurationToISO('2:05')).toBe('PT2H5M');
  });

  it('parses decimal hours', () => {
    expect(parseDurationToISO('1.5')).toBe('PT1H30M');
    expect(parseDurationToISO('0.25')).toBe('PT0H15M');
  });

  it('returns false for unparseable input', () => {
    expect(parseDurationToISO('abc')).toBe(false);
    expect(parseDurationToISO('1:2:3')).toBe(false);
  });
});

describe('formatDuration', () => {
  it('returns a dash for falsy input', () => {
    expect(formatDuration('')).toBe('-');
    expect(formatDuration(null)).toBe('-');
  });

  it('formats hours and minutes, dropping a zero hour', () => {
    expect(formatDuration('1:30:00')).toBe('1h 30m');
    expect(formatDuration('0:45:00')).toBe('45m');
  });

  it('folds a leading day count into hours', () => {
    expect(formatDuration('2 03:00:00')).toBe('51h 0m');
  });
});

describe('parseDurationToHours', () => {
  it('parses decimal hours and HH:MM to 2dp hours', () => {
    expect(parseDurationToHours('1.5')).toBe(1.5);
    expect(parseDurationToHours('1:30')).toBe(1.5);
    expect(parseDurationToHours('0:50')).toBe(0.83);
  });
  it('passes through null/false sentinels', () => {
    expect(parseDurationToHours('')).toBeNull();
    expect(parseDurationToHours('abc')).toBe(false);
  });
});

describe('durationToHours', () => {
  it('handles DRF HH:MM:SS, D HH:MM:SS and ISO', () => {
    expect(durationToHours('01:30:00')).toBe(1.5);
    expect(durationToHours('1 02:00:00')).toBe(26);
    expect(durationToHours('PT1H30M')).toBe(1.5);
    expect(durationToHours(null)).toBeNull();
  });
});

describe('formatSessionDateTime', () => {
  // Session timestamps: day name + time within the last week, calendar
  // date + time beyond it (day names are ambiguous past 7 days), year
  // appended when it isn't the current year.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-16T12:00:00'));
  });
  afterEach(() => { vi.useRealTimers(); });

  it('uses the day name within the last week', () => {
    expect(formatSessionDateTime('2026-03-14T14:05:00')).toBe('Sat 2:05 PM');
  });

  it('uses the calendar date beyond a week', () => {
    expect(formatSessionDateTime('2026-03-01T14:05:00')).toBe('Mar 1, 2:05 PM');
  });

  it('appends the year for other years', () => {
    expect(formatSessionDateTime('2025-12-30T09:30:00')).toBe('Dec 30 2025, 9:30 AM');
  });

  it('dashes out missing timestamps', () => {
    expect(formatSessionDateTime(null)).toBe('—');
  });
});
