import { describe, it, expect } from 'vitest';
import { buildEstimateDocItems } from '@/lib/estimateDocs.js';

describe('buildEstimateDocItems labels', () => {
  it('labels estimates and change orders by their full codes, consistently', () => {
    // House convention: subnav pills carry the full document identity
    // (invoices already do). An estimate's full form is
    // `{estimate_number}-{version}` — the same display the panel's facts
    // table and estimates-and-prices.md use — so it matches the COs' full
    // change_order_number instead of a bare `v2`.
    const items = buildEstimateDocItems({
      estimates: [
        { estimate_id: 7, estimate_number: 'JOB-2026-0012', version: 1, status: 'superseded' },
        { estimate_id: 8, estimate_number: 'JOB-2026-0012', version: 2, status: 'accepted' },
      ],
      changeOrders: [
        { change_order_id: 3, change_order_number: 'CO-2026-0003', status: 'draft' },
      ],
      jobId: 9,
      currentKey: 'est-8',
    });
    expect(items.map((i) => i.label)).toEqual([
      'JOB-2026-0012-1', 'JOB-2026-0012-2', 'CO-2026-0003',
    ]);
  });

  it('falls back to ids when numbers are missing', () => {
    const items = buildEstimateDocItems({
      estimates: [{ estimate_id: 7, version: 1, status: 'draft' }],
      changeOrders: [{ change_order_id: 3, status: 'draft' }],
      jobId: 9,
    });
    expect(items[0].label).toBe('v1');
    expect(items[1].label).toBe('CO #3');
  });
});
