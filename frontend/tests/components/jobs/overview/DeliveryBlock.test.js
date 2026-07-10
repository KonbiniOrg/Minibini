import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import DeliveryBlock from '@/components/jobs/overview/DeliveryBlock.svelte';
import { deliveryBlock } from '@/lib/jobOverview.js';

describe('DeliveryBlock', () => {
  it('active — a prepared shipment awaits pickup', () => {
    const props = {
      shipments: [{ status: 'prepared', prepared_date: '2025-07-01' }],
      deliverableCount: 2,
      job: { status: 'in_progress' },
      now: '2025-07-09',
    };
    const expected = deliveryBlock(props);
    const { container, getByText } = render(DeliveryBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('active');
    expect(getByText('Delivery')).toBeInTheDocument();
    expect(getByText(expected.clock.lines[0])).toBeInTheDocument();
  });

  it('dormant — nothing ready yet', () => {
    const props = { shipments: [], deliverableCount: 0, job: { status: 'in_progress' }, now: '2025-07-09' };
    const expected = deliveryBlock(props);
    const { container, getByText } = render(DeliveryBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('dormant');
    expect(getByText(expected.dormantText)).toBeInTheDocument();
  });
});
