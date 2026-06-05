import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from '@testing-library/svelte';
import ShiftLogTable from '@/components/time/ShiftLogTable.svelte';
import ShiftLogTableHarness from './_ShiftLogTableHarness.svelte';

const closed = {
  shift_id: 1, start_time: '2026-03-16T08:00:00', end_time: '2026-03-16T16:00:00',
};

afterEach(() => {
  vi.useRealTimers();
});

describe('ShiftLogTable', () => {
  it('renders a shift duration', () => {
    const { getByText } = render(ShiftLogTable, { props: { shifts: [closed] } });
    expect(getByText('8h 0m')).toBeInTheDocument();
  });

  it('marks an open shift as open', () => {
    const { getByText } = render(ShiftLogTable, {
      props: { shifts: [{ shift_id: 2, start_time: '2026-03-16T08:00:00' }] },
    });
    expect(getByText('open')).toBeInTheDocument();
  });

  it('shows the worker column when asked', () => {
    const { getByText } = render(ShiftLogTable, {
      props: { shifts: [{ ...closed, user_name: 'Dana' }], showWorker: true },
    });
    expect(getByText('Dana')).toBeInTheDocument();
  });

  it('advances an open shift duration on the tick', async () => {
    const fixedNow = new Date('2026-03-16T09:00:00').getTime();
    vi.useFakeTimers();
    vi.setSystemTime(fixedNow);

    const { getByText } = render(ShiftLogTable, {
      props: { shifts: [{ shift_id: 3, start_time: new Date(fixedNow - 60000).toISOString() }] },
    });
    expect(getByText('1m')).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(30000);
    expect(getByText('2m')).toBeInTheDocument();
  });

  it('renders a per-row actions snippet', () => {
    const { getByRole } = render(ShiftLogTableHarness, { props: { shifts: [closed] } });
    expect(getByRole('button', { name: /Edit/ })).toBeInTheDocument();
  });
});
