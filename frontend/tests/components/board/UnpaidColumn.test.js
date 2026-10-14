import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';

import UnpaidColumn from '@/components/board/UnpaidColumn.svelte';

function job(id, status, sub_status, invoices = []) {
  return {
    job_id: id, job_number: `JOB-${id}`, name: `Job ${id}`, status, sub_status,
    invoices, billed: 0, spent: 0, profit: 0,
  };
}
const inv = (status) => ({ invoice_id: 1, display_number: 'INV-1', status, total: '10.00' });

// Section headers + card numbers in DOM order, so ordering assertions read
// as one flat list.
function flow(container) {
  return Array.from(container.querySelectorAll('.section-label, .border-num'))
    .map(el => el.textContent.trim());
}

describe('UnpaidColumn sections', () => {
  it('groups cards by invoice state in column order, each under its header', () => {
    const { container } = render(UnpaidColumn, {
      props: { jobs: [
        job(1, 'work_complete', 'invoice-sent', [inv('open')]),
        job(2, 'work_complete', 'needs-invoice'),
        job(3, 'work_complete', 'invoice-prepped', [inv('draft')]),
        job(4, 'work_complete', 'needs-invoice'),
      ] },
    });
    expect(flow(container)).toEqual([
      'Needs Invoice', 'JOB-2', 'JOB-4',
      'Invoice Drafted', 'JOB-3',
      'Awaiting Payment', 'JOB-1',
    ]);
  });

  it('renders no header for an empty section', () => {
    const { container, queryByText } = render(UnpaidColumn, {
      props: { jobs: [job(1, 'work_complete', 'invoice-sent', [inv('open')])] },
    });
    expect(queryByText('Needs Invoice')).toBeNull();
    expect(queryByText('Invoice Drafted')).toBeNull();
    expect(flow(container)).toEqual(['Awaiting Payment', 'JOB-1']);
  });

  it('buckets non-work_complete cards (in_progress, cancelled, held) by their invoices', () => {
    const { container } = render(UnpaidColumn, {
      props: { jobs: [
        job(1, 'in_progress', 'in-progress', [inv('draft')]),
        job(2, 'cancelled', null, [inv('open')]),
        job(3, 'work_complete', 'on-hold', [inv('paid')]),
      ] },
    });
    expect(flow(container)).toEqual([
      'Needs Invoice', 'JOB-3',
      'Invoice Drafted', 'JOB-1',
      'Awaiting Payment', 'JOB-2',
    ]);
  });

  it('tints each header with its cards\' tab color', () => {
    const { container } = render(UnpaidColumn, {
      props: { jobs: [
        job(1, 'work_complete', 'needs-invoice'),
        job(2, 'work_complete', 'invoice-prepped', [inv('draft')]),
        job(3, 'work_complete', 'invoice-sent', [inv('open')]),
      ] },
    });
    const colors = Array.from(container.querySelectorAll('.section-divider'))
      .map(el => el.style.getPropertyValue('--section-color').trim());
    expect(colors).toEqual(['#64748b', '#f59e0b', '#3b82f6']);
  });

  it('shows the empty message and no headers when there are no jobs', () => {
    const { container, getByText } = render(UnpaidColumn, { props: { jobs: [] } });
    expect(getByText('No unpaid jobs')).toBeInTheDocument();
    expect(container.querySelector('.section-label')).toBeNull();
  });
});
