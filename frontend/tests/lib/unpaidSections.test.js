import { describe, it, expect } from 'vitest';
import { UNPAID_SECTIONS, unpaidSectionColor } from '@/lib/unpaidSections.js';

describe('UNPAID_SECTIONS', () => {
  it('lists the four groups in column order, Needs Pickup last', () => {
    expect(UNPAID_SECTIONS.map((s) => s.key)).toEqual([
      'needs-invoice', 'invoice-prepped', 'invoice-sent', 'needs-pickup',
    ]);
    expect(UNPAID_SECTIONS.map((s) => s.label)).toEqual([
      'Needs Invoice', 'Invoice Drafted', 'Awaiting Payment', 'Needs Pickup',
    ]);
  });

  it('maps each key to its tab color, with a neutral fallback', () => {
    expect(unpaidSectionColor('needs-invoice')).toBe('#64748b');
    expect(unpaidSectionColor('invoice-prepped')).toBe('#f59e0b');
    expect(unpaidSectionColor('invoice-sent')).toBe('#3b82f6');
    expect(unpaidSectionColor('needs-pickup')).toBe('#7c3aed');
    expect(unpaidSectionColor(undefined)).toBe('#94a3b8');
  });
});
