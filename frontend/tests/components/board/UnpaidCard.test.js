import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import UnpaidCard from '@/components/board/UnpaidCard.svelte';

// sub_status 'needs-invoice' renders the simple block (no invoice table),
// keeping the fixture minimal for these display assertions.
const baseJob = {
  job_number: 'JOB-1', name: 'Widget', contact_id: 5, contact_name: 'Acme',
  sub_status: 'needs-invoice', invoices: [], billed: 0, spent: 0, profit: 0,
};

describe('UnpaidCard project manager line', () => {
  it('shows "PM: <name>" under the customer when a PM is set', () => {
    const { getByText } = render(UnpaidCard, {
      props: { job: { ...baseJob, project_manager_name: 'Rachel McConnell' } },
    });
    expect(getByText('PM: Rachel McConnell')).toBeInTheDocument();
  });

  it('renders no PM line when there is no PM', () => {
    const { container } = render(UnpaidCard, { props: { job: { ...baseJob } } });
    expect(container.querySelector('.pm-line')).toBeNull();
  });
});
