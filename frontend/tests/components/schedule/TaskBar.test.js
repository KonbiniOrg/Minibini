import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import TaskBar from '@/components/schedule/TaskBar.svelte';

const panelStart = new Date('2026-03-01T08:00:00Z');
const panelEnd = new Date('2026-03-01T18:00:00Z');
const timeToX = (iso) => new Date(iso).getUTCHours() * 10;

function bar(overrides) {
  return {
    task_id: 5, name: 'Cut', job_id: 3, kind: 'forecast', accent_color: '#446688',
    status: 'pending', is_running: false, est_minutes: 60, elapsed_minutes: 0,
    segments: [{ start: '2026-03-01T09:00:00Z', end: '2026-03-01T10:00:00Z' }], ...overrides,
  };
}

describe('TaskBar', () => {
  it('renders a bar for an in-range segment with its label', () => {
    const { container, getByText } = render(TaskBar, { props: { bar: bar(), timeToX, panelStart, panelEnd } });
    expect(container.querySelectorAll('.task-bar')).toHaveLength(1);
    expect(getByText('Cut')).toBeInTheDocument();
  });

  it('filters out segments outside the panel range', () => {
    const { container } = render(TaskBar, {
      props: {
        bar: bar({ segments: [{ start: '2026-02-01T09:00:00Z', end: '2026-02-01T10:00:00Z' }] }),
        timeToX, panelStart, panelEnd,
      },
    });
    expect(container.querySelectorAll('.task-bar')).toHaveLength(0);
  });

  it('selects on click', async () => {
    const onSelect = vi.fn();
    const { container } = render(TaskBar, { props: { bar: bar(), timeToX, panelStart, panelEnd, onSelect } });
    await fireEvent.click(container.querySelector('.task-bar'));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ task_id: 5 }));
  });

  it('writes the drag payload and notifies on dragstart', async () => {
    const onDragStart = vi.fn();
    const setData = vi.fn();
    const { container } = render(TaskBar, { props: { bar: bar(), timeToX, panelStart, panelEnd, onDragStart } });
    await fireEvent.dragStart(container.querySelector('.task-bar'), {
      dataTransfer: { setData, effectAllowed: '', setDragImage: vi.fn() },
    });
    expect(setData).toHaveBeenCalledWith('text/plain', '5');
    expect(onDragStart).toHaveBeenCalledWith(5);
  });
});
