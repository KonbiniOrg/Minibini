import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import JobNavRail from '@/components/jobs/JobNavRail.svelte';

// Plain job payload — no nav_targets. The rail no longer reads server-computed
// document targets; every section is a static, always-valid job-scoped link.
const job = { job_id: 3 };

describe('JobNavRail', () => {
  it('renders all eight section links with the right hrefs', () => {
    const { getByRole } = render(JobNavRail, { props: { job, current: 'tasks' } });
    expect(getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '#/jobs/3');
    expect(getByRole('link', { name: 'Estimates' })).toHaveAttribute('href', '#/jobs/3/estimate');
    expect(getByRole('link', { name: 'Tasks' })).toHaveAttribute('href', '#/jobs/3/tasks');
    expect(getByRole('link', { name: 'Invoices' })).toHaveAttribute('href', '#/jobs/3/invoice');
    expect(getByRole('link', { name: 'Shipments' })).toHaveAttribute('href', '#/jobs/3/shipments');
    expect(getByRole('link', { name: 'POs' })).toHaveAttribute('href', '#/jobs/3/pos');
    expect(getByRole('link', { name: 'Emails' })).toHaveAttribute('href', '#/jobs/3/emails');
    expect(getByRole('link', { name: 'History' })).toHaveAttribute('href', '#/jobs/3/history');
  });

  it('marks the current section active, including overview', () => {
    const { getByRole } = render(JobNavRail, { props: { job, current: 'overview' } });
    expect(getByRole('link', { name: 'Overview' })).toHaveClass('active');
    expect(getByRole('link', { name: 'Tasks' })).not.toHaveClass('active');
  });

  it('marks a non-overview section active', () => {
    const { getByRole } = render(JobNavRail, { props: { job, current: 'invoice' } });
    expect(getByRole('link', { name: 'Invoices' })).toHaveClass('active');
    expect(getByRole('link', { name: 'Overview' })).not.toHaveClass('active');
  });

  it('never dims or disables a section, even with no documents on the job', () => {
    const { container, getAllByRole } = render(JobNavRail, { props: { job, current: 'tasks' } });
    expect(container.querySelectorAll('.empty').length).toBe(0);
    const links = getAllByRole('link');
    expect(links.length).toBe(8);
    for (const l of links) {
      expect(l.tagName).toBe('A');
      expect(l).toHaveAttribute('href');
    }
  });

  it('puts the seam divider on the Emails entry', () => {
    const { getByRole } = render(JobNavRail, { props: { job, current: 'tasks' } });
    expect(getByRole('link', { name: 'Emails' })).toHaveClass('seam');
  });
});
