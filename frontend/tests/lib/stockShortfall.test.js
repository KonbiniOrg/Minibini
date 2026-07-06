import { describe, it, expect } from 'vitest';
import { stockShortfall } from '@/lib/stockShortfall.js';

describe('stockShortfall', () => {
  it('uses qty_earmarked on inventory rows', () => {
    expect(stockShortfall({ qty_earmarked: '6', qty_on_hand: '1', qty_on_order: '2' }))
      .toBe('3');
  });
  it('prefers qty_earmarked_total on earmark rows', () => {
    expect(stockShortfall({
      qty_earmarked_total: '6', qty_earmarked: '999',
      qty_on_hand: '1', qty_on_order: '2',
    })).toBe('3');
  });
  it('floors at zero when stock covers', () => {
    expect(stockShortfall({ qty_earmarked: '2', qty_on_hand: '5', qty_on_order: '0' }))
      .toBe('0');
  });
});
