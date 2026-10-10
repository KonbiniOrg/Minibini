import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';

// Real svelte-spa-router so use:link rewrites hrefs to hash routes.
import RecentTaskList from '@/components/home/RecentTaskList.svelte';
import { viewMode } from '@/stores/viewMode.js';

const task = (id, name, extra = {}) => ({
  id, name, status: 'complete',
  job: { id: 7, job_number: 'JOB-2026-0007', name: 'Chairs' },
  last_worked_at: '2026-07-10T14:00:00Z', ...extra,
});

describe('RecentTaskList', () => {
  it('shows the empty state and the window note', () => {
    const { getByText } = render(RecentTaskList, { props: { tasks: [], sinceDays: 5 } });
    expect(getByText('No recently completed tasks.')).toBeInTheDocument();
    expect(getByText('(completed in the past 5 days)')).toBeInTheDocument();
  });

  it('renders completed tasks linking to the task and job', () => {
    const { getByRole } = render(RecentTaskList, {
      props: { tasks: [task(5, 'Sand')], sinceDays: 5 },
    });
    expect(getByRole('link', { name: 'Sand' }).getAttribute('href')).toBe('#/jobs/7/tasks/5');
    expect(getByRole('link', { name: /JOB-2026-0007/ }).getAttribute('href')).toBe('#/jobs/7');
  });

  it('offers no Start Work or reorder controls (read-only)', () => {
    const { queryByRole } = render(RecentTaskList, {
      props: { tasks: [task(5, 'Sand')], sinceDays: 5 },
    });
    expect(queryByRole('button', { name: 'Start Work' })).toBeNull();
    expect(queryByRole('button', { name: 'Up' })).toBeNull();
  });
});

describe('RecentTaskList — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  it('renders Task / Job / Last worked in both densities with data-col', () => {
    viewMode.set('lite');
    const { container } = render(RecentTaskList, { props: { tasks: [task(1, 'Sand')], sinceDays: 5 } });
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(['Task', 'Job', 'Last worked']);
    // Real svelte-spa-router `use:link` in this test file rewrites the href with the hash prefix.
    expect(table.querySelector('td[data-col="task"] a')).toHaveAttribute('href', '#/jobs/7/tasks/1');
    viewMode.set('full');
    const { container: c2 } = render(RecentTaskList, { props: { tasks: [task(1, 'Sand')], sinceDays: 5 } });
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(['Task', 'Job', 'Last worked']);
  });
});
