import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import JobNavRail from '@/components/jobs/JobNavRail.svelte';

const job = {
  job_id: 5,
  nav_targets: { estimate: 11, invoice: 22, po: 33 },
};

describe('JobNavRail', () => {
  it('links back to the overview and to each category target', () => {
    const { getByRole } = render(JobNavRail, { props: { job, current: 'estimate' } });
    expect(getByRole('link', { name: /Overview/ })).toHaveAttribute('href', '#/jobs/5');
    expect(getByRole('link', { name: 'Estimate' })).toHaveAttribute('href', '#/estimates/11');
    expect(getByRole('link', { name: 'Tasks' })).toHaveAttribute('href', '#/jobs/5/tasklist');
    expect(getByRole('link', { name: 'Invoice' })).toHaveAttribute('href', '#/invoices/22');
    expect(getByRole('link', { name: 'Shipments' })).toHaveAttribute('href', '#/jobs/5/shipments');
    expect(getByRole('link', { name: 'POs' })).toHaveAttribute('href', '#/purchase-orders/33');
  });

  it('marks the current section active', () => {
    const { getByRole } = render(JobNavRail, { props: { job, current: 'invoice' } });
    expect(getByRole('link', { name: 'Invoice' })).toHaveClass('active');
    expect(getByRole('link', { name: 'Estimate' })).not.toHaveClass('active');
  });

  it('dims document categories with no target instead of hiding them', () => {
    const bare = { job_id: 5, nav_targets: { estimate: null, invoice: null, po: null } };
    const { getByText, queryByRole, getByRole } = render(JobNavRail, { props: { job: bare, current: 'tasks' } });
    expect(queryByRole('link', { name: 'Estimate' })).toBeNull();
    expect(getByText('Estimate')).toBeInTheDocument();
    expect(getByText('Invoice')).toBeInTheDocument();
    expect(getByText('POs')).toBeInTheDocument();
    // Job-scoped pages always link, documents or not.
    expect(getByRole('link', { name: 'Tasks' })).toBeInTheDocument();
    expect(getByRole('link', { name: 'Shipments' })).toBeInTheDocument();
  });

  it('tolerates a job payload without nav_targets (all documents dimmed)', () => {
    const { queryByRole, getByRole } = render(JobNavRail, { props: { job: { job_id: 5 } } });
    expect(queryByRole('link', { name: 'Estimate' })).toBeNull();
    expect(getByRole('link', { name: 'Tasks' })).toBeInTheDocument();
  });
});
