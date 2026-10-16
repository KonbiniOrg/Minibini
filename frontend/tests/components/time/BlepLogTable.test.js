import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import BlepLogTable from '@/components/time/BlepLogTable.svelte';
import BlepLogTableHarness from './_BlepLogTableHarness.svelte';
import { viewMode } from '@/stores/viewMode.js';

const closed = {
  blep_id: 1, task_name: 'Cutting', job_id: 7, job_number: 'JOB-7', job_name: 'Widget',
  task: 3, start_time: '2026-03-16T14:00:00', end_time: '2026-03-16T15:00:00',
};

afterEach(() => {
  vi.useRealTimers();
});

describe('BlepLogTable', () => {
  it('renders a session row', () => {
    const { getByText } = render(BlepLogTable, { props: { bleps: [closed] } });
    expect(getByText('Cutting')).toBeInTheDocument();
    expect(getByText('1h 0m')).toBeInTheDocument();
  });

  it('marks an open blep as active', () => {
    const { getByText } = render(BlepLogTable, {
      props: { bleps: [{ blep_id: 2, task_name: 'Live', start_time: '2026-03-16T14:00:00' }] },
    });
    expect(getByText('active')).toBeInTheDocument();
  });

  it('shows the worker column when asked', () => {
    const { getByText } = render(BlepLogTable, {
      props: { bleps: [{ ...closed, user_name: 'Sam' }], showWorker: true },
    });
    expect(getByText('Sam')).toBeInTheDocument();
  });

  it('advances an open blep duration on the tick', async () => {
    const fixedNow = new Date('2026-03-16T15:00:00').getTime();
    vi.useFakeTimers();
    vi.setSystemTime(fixedNow);

    const { getByText } = render(BlepLogTable, {
      props: { bleps: [{ blep_id: 3, task_name: 'Open', start_time: new Date(fixedNow - 60000).toISOString() }] },
    });
    expect(getByText('1m')).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(30000);
    expect(getByText('2m')).toBeInTheDocument();
  });

  it('renders a per-row actions snippet', () => {
    const { getByRole } = render(BlepLogTableHarness, { props: { bleps: [closed] } });
    expect(getByRole('button', { name: /Edit/ })).toBeInTheDocument();
  });
});

describe('BlepLogTable timestamp convention', () => {
  it('shows the calendar date instead of the day name past a week', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-16T12:00:00'));
    const { getByText, queryByText } = render(BlepLogTable, {
      props: { bleps: [{ ...closed, start_time: '2026-03-01T14:00:00', end_time: '2026-03-01T15:00:00' }] },
    });
    expect(getByText('Mar 1, 2:00 PM')).toBeInTheDocument();
    expect(queryByText(/^Sun 2:00 PM$/)).toBeNull();
  });
});

describe('BlepLogTable — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  it('renders the base columns in both densities, adding Worker and an actions column only when asked', () => {
    viewMode.set('lite');
    const { container } = render(BlepLogTable, { props: { bleps: [closed] } });
    expect(headersOf(container.querySelector('table.data-table'))).toEqual(['Task', 'Job', 'Start', 'End', 'Duration']);
    expect(container.querySelector('td[data-col="task"] a')).toHaveAttribute('href', '/jobs/7/tasks/3');
    const { container: c2 } = render(BlepLogTable, { props: { bleps: [{ ...closed, user_name: 'Wanda' }], showWorker: true } });
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(['Worker', 'Task', 'Job', 'Start', 'End', 'Duration']);
    expect(c2.querySelector('td[data-col="worker"]').textContent.trim()).toBe('Wanda');
    viewMode.set('full');
    const { container: c3 } = render(BlepLogTableHarness, { props: { bleps: [closed] } });
    expect(headersOf(c3.querySelector('table.data-table'))).toEqual(['Task', 'Job', 'Start', 'End', 'Duration', '']);
    expect(c3.querySelector('td[data-col="actions"] button').textContent).toBe('Edit 1');
  });
});
