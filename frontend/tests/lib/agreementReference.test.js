import { describe, it, expect } from 'vitest';
import { coShortLabel, estReferenceText } from '@/lib/agreementReference.js';

describe('coShortLabel', () => {
  it('derives "CO-1" from a trailing "-CO<n>" suffix', () => {
    expect(coShortLabel('EST-2026-0004-CO1')).toBe('CO-1');
  });

  it('handles multi-digit CO counters', () => {
    expect(coShortLabel('EST-2026-0004-CO12')).toBe('CO-12');
  });

  it('falls back to the full number when the suffix is absent', () => {
    expect(coShortLabel('EST-2026-0004')).toBe('EST-2026-0004');
  });

  it('is null-safe', () => {
    expect(coShortLabel(null)).toBe('');
    expect(coShortLabel(undefined)).toBe('');
    expect(coShortLabel('')).toBe('');
  });
});

describe('estReferenceText', () => {
  it('returns "" when the line has no agreement_ref', () => {
    expect(estReferenceText({ agreement_ref: null, qty: '1', price: '1' })).toBe('');
  });

  it('reads "{coShortLabel} line {co_line_number}" for a CO-origin ref, no est-was clause', () => {
    const li = {
      qty: '3', price: '40.00', actuals_total: null,
      agreement_ref: {
        kind: 'change_order', line_id: 9,
        est_qty: '3', est_price: '40.00', est_amount: '120.00',
        co_number: 'EST-2026-0004-CO1', co_line_number: 2,
      },
    };
    expect(estReferenceText(li)).toBe('CO-1 line 2');
  });

  it('falls back to the full CO number in the reference text when the suffix is absent', () => {
    const li = {
      qty: '1', price: '10.00', actuals_total: null,
      agreement_ref: {
        kind: 'change_order', line_id: 9,
        est_qty: '1', est_price: '10.00', est_amount: '10.00',
        co_number: 'CO-SB-1', co_line_number: 1,
      },
    };
    expect(estReferenceText(li)).toBe('CO-SB-1 line 1');
  });

  it('leaves estimate-origin reference text unchanged: "est was $X" with no delta clause at Δ=0', () => {
    const li = {
      qty: '2', price: '25.00', actuals_total: null,
      agreement_ref: { kind: 'estimate', line_id: 30, est_qty: '2', est_price: '25.00', est_amount: '50.00' },
    };
    expect(estReferenceText(li)).toBe('est was $50.00');
  });

  it('estimate-origin: appends "· +$Δ" when the current amount diverges from the estimate', () => {
    const li = {
      qty: '2', price: '25.00', actuals_total: '55.00',
      agreement_ref: { kind: 'estimate', line_id: 30, est_qty: '2', est_price: '25.00', est_amount: '50.00' },
    };
    expect(estReferenceText(li)).toBe('est was $50.00 · +$5.00');
  });
});
