import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/stores/schedule.js', async () => {
  const { writable } = await import('svelte/store');
  return { reorderTasksInLane: vi.fn(), draggingTaskId: writable(null) };
});

import { reorderTasksInLane } from '@/stores/schedule.js';
import WorkerLane from '@/components/schedule/WorkerLane.svelte';

function fbar(task_id, name) {
  return {
    task_id, name, kind: 'forecast', job_id: 1, accent_color: '#888', status: 'pending', is_running: false,
    est_minutes: 60, elapsed_minutes: 0,
    segments: [{ start: '2026-03-01T09:00:00Z', end: '2026-03-01T10:00:00Z' }],
  };
}

const panelLayout = {
  timeToX: (t) => new Date(t).getUTCHours(),
  start: new Date('2026-03-01T00:00:00Z'),
  end: new Date('2026-03-01T23:00:00Z'),
};

beforeEach(() => {
  reorderTasksInLane.mockReset();
});

describe('WorkerLane', () => {
  it('renders the worker and their bars', () => {
    const worker = { user: { id: 1, name: 'Sam', initials: 'S' }, bars: [fbar(20, 'T20')] };
    const { getByText } = render(WorkerLane, { props: { worker, panelLayout } });
    expect(getByText('Sam')).toBeInTheDocument();
    expect(getByText('T20')).toBeInTheDocument();
  });

  it('reorders the lane on drop', async () => {
    const worker = { user: { id: 1, name: 'Sam', initials: 'S' }, bars: [fbar(20, 'T20'), fbar(30, 'T30')] };
    const { container } = render(WorkerLane, { props: { worker, panelLayout } });
    const track = container.querySelector('.track');
    // drop task 10 far to the right → appended after the existing queue [20, 30]
    await fireEvent.drop(track, { dataTransfer: { getData: () => '10' }, clientX: 1000 });
    expect(reorderTasksInLane).toHaveBeenCalledWith(1, [20, 30, 10]);
  });
});
