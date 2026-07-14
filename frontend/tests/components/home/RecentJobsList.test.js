import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';

// Real svelte-spa-router so use:link rewrites hrefs to hash routes.
import RecentJobsList from '@/components/home/RecentJobsList.svelte';

describe('RecentJobsList', () => {
  it('shows the empty state and the window note', () => {
    const { getByText } = render(RecentJobsList, { props: { jobs: [], sinceDays: 5 } });
    expect(getByText('No recent jobs.')).toBeInTheDocument();
    expect(getByText('(past 5 days)')).toBeInTheDocument();
  });

  it('renders jobs as table rows linking to the job', () => {
    const jobs = [
      { id: 7, job_number: 'JOB-2026-0007', name: 'Chairs', last_worked_at: '2026-07-10T14:00:00Z' },
    ];
    const { getByRole } = render(RecentJobsList, { props: { jobs, sinceDays: 5 } });
    const link = getByRole('link', { name: 'JOB-2026-0007' });
    expect(link.getAttribute('href')).toBe('#/jobs/7');
    expect(getByRole('cell', { name: 'Chairs' })).toBeInTheDocument();
  });
});
