import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import InvoicingBlock from '@/components/jobs/overview/InvoicingBlock.svelte';
import { invoicingBlock } from '@/lib/jobOverview.js';

describe('InvoicingBlock', () => {
  it('active — renders a per-invoice stat with its latency sub', () => {
    const props = {
      invoices: [
        { invoice_number: 'INV-0088', status: 'paid', total: 3000, sent_date: '2025-06-24', closed_date: '2025-06-28' },
      ],
      scopeTotal: 12400,
      invoicedTotal: 3000,
      now: '2025-07-09',
    };
    const expected = invoicingBlock(props);
    const { container, getByText } = render(InvoicingBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('active');
    expect(getByText('Invoicing')).toBeInTheDocument();
    expect(getByText('INV-0088')).toBeInTheDocument();
    expect(getByText(expected.stats[0].sub)).toBeInTheDocument();
  });

  it('dormant — no live invoices', () => {
    const props = { invoices: [], scopeTotal: 12400, now: '2025-07-09' };
    const expected = invoicingBlock(props);
    const { container, getByText } = render(InvoicingBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('dormant');
    expect(getByText(expected.dormantText)).toBeInTheDocument();
  });
});
