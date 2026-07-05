import { describe, it, expect } from 'vitest';
import { materialStatus, costUnconfirmed } from '../src/lib/materialStatus.js';

const base = {
  inventory_item: 7, cost_source: 'entered', consumption_state: 'pending',
  quantity: '4.00', qty_on_hand: '0.00', po_line_item_id: null, po_number: null,
};

describe('materialStatus', () => {
  it('released and consumed win over everything', () => {
    expect(materialStatus({ ...base, consumption_state: 'released' }).key).toBe('released');
    expect(materialStatus({ ...base, consumption_state: 'consumed' }).key).toBe('consumed');
  });
  it('provisional → needs-pricing', () => {
    expect(materialStatus({ ...base, inventory_item: null, cost_source: null }).key)
      .toBe('needs-pricing');
  });
  it('customer short → awaiting-customer', () => {
    expect(materialStatus({ ...base, cost_source: 'customer_supplied' }).key)
      .toBe('awaiting-customer');
  });
  it('stock covers → on-hand (incl. customer)', () => {
    expect(materialStatus({ ...base, qty_on_hand: '4.00' }).key).toBe('on-hand');
    expect(materialStatus({ ...base, cost_source: 'customer_supplied', qty_on_hand: '5.00' }).key)
      .toBe('on-hand');
  });
  it('linked PO → ordered with number in label', () => {
    const s = materialStatus({ ...base, po_line_item_id: 3, po_number: 'PO-2026-0042' });
    expect(s.key).toBe('ordered');
    expect(s.label).toContain('PO-2026-0042');
  });
  it('established + short + unlinked → needed', () => {
    expect(materialStatus(base).key).toBe('needed');
  });
  it('costUnconfirmed only for estimated', () => {
    expect(costUnconfirmed({ ...base, cost_source: 'estimated' })).toBe(true);
    expect(costUnconfirmed(base)).toBe(false);
  });
});
