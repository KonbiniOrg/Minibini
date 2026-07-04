import { describe, it, expect } from 'vitest';
import { orderPrefillQty } from '@/lib/materials.js';

describe('orderPrefillQty', () => {
  it('defaults to the shortfall (needed minus on hand)', () => {
    expect(orderPrefillQty({ quantity: '5.00', qty_on_hand: '2.00' })).toBe('3');
  });

  it('falls back to the full quantity when nothing is short', () => {
    expect(orderPrefillQty({ quantity: '5.00', qty_on_hand: '9.00' })).toBe('5.00');
  });

  it('treats a freeform material (no stock data) as fully short', () => {
    expect(orderPrefillQty({ quantity: '4.00', qty_on_hand: '0' })).toBe('4');
    expect(orderPrefillQty({ quantity: '4.00' })).toBe('4');
  });
});
