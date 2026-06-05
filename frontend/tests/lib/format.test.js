import { describe, it, expect } from 'vitest';
import { formatQtyUnits, parseDurationToISO, formatDuration } from '@/lib/format.js';

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
