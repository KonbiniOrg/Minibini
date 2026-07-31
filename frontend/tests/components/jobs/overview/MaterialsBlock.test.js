import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import MaterialsBlock from '@/components/jobs/overview/MaterialsBlock.svelte';
import { materialsBlock } from '@/lib/jobOverview.js';

describe('MaterialsBlock', () => {
  it('active — renders an open PO stat with its due date', () => {
    const props = {
      pos: [
        {
          status: 'issued',
          po_number: 'PO-0031',
          business_name: 'Plywood Supply Co',
          issued_date: '2025-06-28',
          requested_date: '2025-07-10',
        },
      ],
      materials: [
        { inventory_item: 7, cost_source: 'entered', consumption_state: 'pending',
          quantity: '4.00', qty_on_hand: '0.00', po_line_item_id: 3, qty_on_order: '4.00' },
      ],
      now: '2025-07-09',
    };
    const expected = materialsBlock(props);
    const { container, getByText } = render(MaterialsBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('active');
    expect(getByText('Materials')).toBeInTheDocument();
    expect(getByText('PO-0031')).toBeInTheDocument();
    // The lib buckets the material (on a live PO line) as not-yet-arrived.
    const cov = expected.stats.find((s) => s.label === 'Coverage');
    expect(cov.value).toBe('WAITING');
    expect(getByText(cov.value)).toBeInTheDocument();
    expect(getByText(cov.sub)).toBeInTheDocument();
  });

  it('dormant — nothing on order', () => {
    const props = { pos: [], materials: [], now: '2025-07-09' };
    const expected = materialsBlock(props);
    const { container, getByText } = render(MaterialsBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('dormant');
    expect(getByText(expected.dormantText)).toBeInTheDocument();
  });

  it('threads jobId into the lib and links the card at the job POs section', () => {
    const props = {
      jobId: 42,
      pos: [{ status: 'issued', po_id: 9, po_number: 'PO-0031', business_name: 'Plywood Supply Co' }],
      materials: [],
      now: '2025-07-09',
    };
    const { container } = render(MaterialsBlock, { props });
    expect(container.querySelector('.summary-block').getAttribute('href')).toBe('#/jobs/42/pos');
  });
});
