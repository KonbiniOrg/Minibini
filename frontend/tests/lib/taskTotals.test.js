import { describe, it, expect } from 'vitest';
import { taskActual, taskTotalInfo, taskTotal, feeTotal, fmtMoney } from '@/lib/taskTotals.js';

// Task-owned money (Phase 1): taskActual branches on the task's own
// qty_source field now, not the retired scheme_algorithm echo.
describe('taskActual', () => {
  it('reads actual_hours for an elapsed_time (timeslip-sourced) task', () => {
    expect(taskActual({ qty_source: 'elapsed_time', actual_hours: '2.50' })).toBe(2.5);
  });

  it('returns null for a zero/absent actual_hours on an elapsed_time task', () => {
    expect(taskActual({ qty_source: 'elapsed_time', actual_hours: 0 })).toBeNull();
    expect(taskActual({ qty_source: 'elapsed_time' })).toBeNull();
  });

  it('reads actual_qty for an entered_qty task', () => {
    expect(taskActual({ qty_source: 'entered_qty', actual_qty: '9.00' })).toBe('9.00');
  });

  it('returns null for an entered_qty task with no actual_qty yet', () => {
    expect(taskActual({ qty_source: 'entered_qty', actual_qty: null })).toBeNull();
    expect(taskActual({ qty_source: 'entered_qty', actual_qty: '' })).toBeNull();
  });

  it('returns null for an unset/unknown qty_source', () => {
    expect(taskActual({ qty_source: null, actual_qty: '5' })).toBeNull();
    expect(taskActual({})).toBeNull();
  });
});

describe('taskTotalInfo / taskTotal (unaffected by the qty_source rename)', () => {
  it('prefers the live computed_charge when present', () => {
    expect(taskTotalInfo({ computed_charge: '40.00', est_qty: '2', effective_rate: '10' }))
      .toEqual({ value: 40, isEstimate: false });
  });

  it('falls back to est_qty * effective_rate, flagged as an estimate', () => {
    expect(taskTotalInfo({ computed_charge: '0.00', est_qty: '2', effective_rate: '10' }))
      .toEqual({ value: 20, isEstimate: true });
  });

  it('returns a zero, non-estimate total with nothing to compute from', () => {
    expect(taskTotalInfo({})).toEqual({ value: 0, isEstimate: false });
    expect(taskTotal({})).toBe(0);
  });
});

describe('feeTotal (signed — a credit fee has a negative unit_rate)', () => {
  it('computes quantity × unit_rate for a charge', () => {
    expect(feeTotal({ quantity: '4', unit_rate: '12.50' })).toBe(50);
  });

  it('computes a negative total for a credit fee (negative unit_rate)', () => {
    expect(feeTotal({ quantity: '2', unit_rate: '-10.00' })).toBe(-20);
  });
});

describe('fmtMoney (negative amounts)', () => {
  it('puts the minus sign before the dollar sign, not after', () => {
    expect(fmtMoney(-80)).toBe('-$80.00');
  });

  it('formats a positive amount normally', () => {
    expect(fmtMoney(80)).toBe('$80.00');
  });
});
