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
      coverage: { tone: 'good', label: 'OK', sub: 'stock + this order' },
      now: '2025-07-09',
    };
    const expected = materialsBlock(props);
    const { container, getByText } = render(MaterialsBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('active');
    expect(getByText('Materials')).toBeInTheDocument();
    expect(getByText('PO-0031')).toBeInTheDocument();
    expect(getByText(expected.stats.find((s) => s.label === 'Coverage').value)).toBeInTheDocument();
  });

  it('dormant — nothing on order', () => {
    const props = { pos: [], coverage: null, now: '2025-07-09' };
    const expected = materialsBlock(props);
    const { container, getByText } = render(MaterialsBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('dormant');
    expect(getByText(expected.dormantText)).toBeInTheDocument();
  });
});
