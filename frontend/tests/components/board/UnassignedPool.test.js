import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import UnassignedPool from '@/components/board/UnassignedPool.svelte';

const TASKS = [
  { task_id: 1, job_id: 2, name: 'Alpha', status: 'pending', job_name: 'J2' },
  { task_id: 2, job_id: 3, name: 'Beta', status: 'pending', job_name: 'J3' },
];

describe('UnassignedPool', () => {
  it('shows all tasks when no jobs are focused', () => {
    const { getByText } = render(UnassignedPool, { props: { tasks: TASKS } });
    expect(getByText('Alpha')).toBeInTheDocument();
    expect(getByText('Beta')).toBeInTheDocument();
  });

  it('filters to the focused jobs', () => {
    const { getByText, queryByText } = render(UnassignedPool, {
      props: { tasks: TASKS, focusedJobIds: [2] },
    });
    expect(getByText('Alpha')).toBeInTheDocument();
    expect(queryByText('Beta')).toBeNull();
  });

  it('shows the all-assigned empty state', () => {
    const { getByText } = render(UnassignedPool, { props: { tasks: [] } });
    expect(getByText('All tasks assigned')).toBeInTheDocument();
  });

  it('shows the focused-empty state when no task matches the focus', () => {
    const { getByText } = render(UnassignedPool, {
      props: { tasks: TASKS, focusedJobIds: [99] },
    });
    expect(getByText('No unassigned tasks for focused jobs')).toBeInTheDocument();
  });

  it('assigns to unassigned (-1) on drop when allowed to manage', async () => {
    const onAssign = vi.fn();
    const { container } = render(UnassignedPool, {
      props: { tasks: TASKS, canManage: true, onAssign },
    });
    const body = container.querySelector('.unassigned-body');
    await fireEvent.drop(body, { dataTransfer: { getData: () => '5' } });
    expect(onAssign).toHaveBeenCalledWith(5, null, -1);
  });

  it('ignores a drop when not allowed to manage', async () => {
    const onAssign = vi.fn();
    const { container } = render(UnassignedPool, {
      props: { tasks: TASKS, canManage: false, onAssign },
    });
    const body = container.querySelector('.unassigned-body');
    await fireEvent.drop(body, { dataTransfer: { getData: () => '5' } });
    expect(onAssign).not.toHaveBeenCalled();
  });
});
