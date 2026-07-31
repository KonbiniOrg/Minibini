import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import ScopeBlock from '@/components/jobs/overview/ScopeBlock.svelte';
import { scopeBlock } from '@/lib/jobOverview.js';

describe('ScopeBlock', () => {
  it('active — renders the current estimate stat spread and response clock', () => {
    const props = {
      estimates: [
        { version: 1, status: 'superseded' },
        { version: 2, status: 'open', sent_date: '2025-06-27', total: '8750.00' },
      ],
      changeOrders: [],
      deliverableCount: 3,
      now: '2025-07-09',
    };
    const expected = scopeBlock(props);
    const { container, getByText } = render(ScopeBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('active');
    expect(getByText('Scope')).toBeInTheDocument();
    expect(getByText('v2')).toBeInTheDocument();
    expect(getByText(expected.clock.lines[0])).toBeInTheDocument();
  });

  it('dormant — no estimate yet', () => {
    const props = { estimates: [], changeOrders: [], deliverableCount: 0, now: '2025-07-09' };
    const expected = scopeBlock(props);
    const { container, getByText } = render(ScopeBlock, { props });
    expect(container.querySelector('.summary-block')).toHaveClass('dormant');
    expect(getByText(expected.dormantText)).toBeInTheDocument();
  });

  it('threads jobId into the lib and links the card at the current estimate', () => {
    const props = {
      jobId: 42,
      estimates: [{ estimate_id: 8, version: 2, status: 'open', sent_date: '2025-06-27' }],
      changeOrders: [],
      deliverableCount: 0,
      now: '2025-07-09',
    };
    const { container } = render(ScopeBlock, { props });
    expect(container.querySelector('.summary-block').getAttribute('href'))
      .toBe('#/jobs/42/estimate/8');
  });
});
