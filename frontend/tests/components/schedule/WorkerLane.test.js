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

// A geometry-bearing layout for the per-lane shading tests: one working day
// panel 0-240px, hours map linearly (10px per hour via the stub).
const shadedLayout = {
  timeToX: (t) => {
    // Date-aware stub: each panel is 240px, hours map at 10px/hour within it.
    const iso = String(t);
    const panelX = iso.startsWith('2026-03-03') ? 240 : 0;
    const [hh, mm] = iso.slice(11, 16).split(':').map(Number);
    return panelX + hh * 10 + mm / 6;
  },
  panels: [
    { date: '2026-03-02', is_working: true, x: 0, width: 240 },
    { date: '2026-03-03', is_working: true, x: 240, width: 240 },
  ],
  start: new Date('2026-03-02T00:00:00Z'),
  end: new Date('2026-03-04T00:00:00Z'),
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

  it('shades the lane outside its own envelope, including gaps', () => {
    const worker = {
      user: { id: 1, name: 'Sam', initials: 'S' },
      bars: [],
      envelope_by_day: [
        [['08:00', '12:00'], ['12:30', '17:00']],  // lunch gap on day 1
        [['08:00', '17:00']],
      ],
    };
    const { container } = render(WorkerLane, {
      props: { worker, panelLayout: shadedLayout, days: [
        { date: '2026-03-02', is_working: true },
        { date: '2026-03-03', is_working: true },
      ] },
    });
    const bands = [...container.querySelectorAll('.lane-offhours')];
    // Day 1: before 08:00, the 12:00-12:30 gap, after 17:00.
    // Day 2: before 08:00, after 17:00. Five bands total.
    expect(bands).toHaveLength(5);
  });

  it('shades the whole panel for a day the worker does not work', () => {
    const worker = {
      user: { id: 1, name: 'Sam', initials: 'S' },
      bars: [],
      envelope_by_day: [
        [],                     // day off for this worker
        [['08:00', '17:00']],
      ],
    };
    const { container } = render(WorkerLane, {
      props: { worker, panelLayout: shadedLayout, days: [
        { date: '2026-03-02', is_working: true },
        { date: '2026-03-03', is_working: true },
      ] },
    });
    const bands = [...container.querySelectorAll('.lane-offhours')];
    // Day 1 fully shaded (one band spanning the panel) + day 2 margins (2).
    expect(bands).toHaveLength(3);
    const widths = bands.map((b) => parseFloat(b.style.width));
    expect(Math.max(...widths)).toBe(240);
  });

  it('renders no shading bands without envelope data', () => {
    const worker = { user: { id: 1, name: 'Sam', initials: 'S' }, bars: [fbar(20, 'T20')] };
    const { container } = render(WorkerLane, { props: { worker, panelLayout } });
    expect(container.querySelectorAll('.lane-offhours')).toHaveLength(0);
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
