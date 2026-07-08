import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import TaskCard from '@/components/board/TaskCard.svelte';

const PAST = '2000-01-01';

describe('TaskCard', () => {
  it('renders the task name and activity badge', () => {
    const { getByText } = render(TaskCard, {
      props: { task: { task_id: 7, job_id: 3, name: 'Cut steel', status: 'in_progress', job_name: 'JobX' } },
    });
    expect(getByText('Cut steel')).toBeInTheDocument();
    expect(getByText('Ongoing')).toBeInTheDocument();
  });

  it('marks a blocked, overdue task as urgent', () => {
    const { container, getByText } = render(TaskCard, {
      props: { task: { task_id: 8, job_id: 3, name: 'Weld', status: 'blocked', job_name: 'JobX', job_due_date: PAST } },
    });
    expect(container.querySelector('.task-card')).toHaveClass('urgent');
    expect(getByText(/overdue/)).toBeInTheDocument();
  });

  it('is not urgent for a non-blocked task', () => {
    const { container } = render(TaskCard, {
      props: { task: { task_id: 9, job_id: 3, name: 'Paint', status: 'pending', job_name: 'JobX' } },
    });
    expect(container.querySelector('.task-card')).not.toHaveClass('urgent');
  });

  it('draws dot and badge colors from the shared taskActivity palette', () => {
    // Working: green #16a34a from lib/taskActivity.js — no hand-copied
    // per-key color classes in the card itself.
    const { container, getByText } = render(TaskCard, {
      props: { task: { task_id: 7, job_id: 3, name: 'Cut steel', status: 'in_progress', has_active_blep: true, job_name: 'JobX' } },
    });
    // Dot is the shared indicator component (compact mode).
    expect(container.querySelector('.ta-dot')).toBeInTheDocument();
    const badge = getByText('Working');
    expect(badge.style.color).toBe('rgb(22, 163, 74)');
  });

  it('writes the task id into the drag payload when draggable', async () => {
    const setData = vi.fn();
    const { container } = render(TaskCard, {
      props: { task: { task_id: 7, job_id: 3, name: 'Cut steel', status: 'pending', job_name: 'JobX' }, draggable: true },
    });
    await fireEvent.dragStart(container.querySelector('.task-card'), {
      dataTransfer: { setData, effectAllowed: '' },
    });
    expect(setData).toHaveBeenCalledWith('text/plain', '7');
  });
});
