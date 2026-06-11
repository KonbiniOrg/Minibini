import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import TaskTree from '@/components/TaskTree.svelte';

function task(overrides) {
  return {
    task_id: 1, name: 'Cut', status: 'pending', est_qty: '2', effective_rate: '25',
    computed_charge: '0', est_worker_time: null, scheme_unit_label: 'hr', materials: [], ...overrides,
  };
}

describe('TaskTree', () => {
  it('renders tasks, materials, and a grand total', () => {
    const t = task({
      materials: [{ description: 'Steel', quantity: '3', sell_price: '5', units: 'kg', consumption_state: 'pending' }],
    });
    // task total 2*25 = $50.00, material 3*5 = $15.00, grand = $65.00
    const { getByText } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(getByText('Cut')).toBeInTheDocument();
    expect(getByText('Steel')).toBeInTheDocument();
    expect(getByText('$65.00')).toBeInTheDocument();
  });

  it('fires the edit callback when canManage', async () => {
    const onEditTask = vi.fn();
    const { getByRole } = render(TaskTree, { props: { tasks: [task()], canManage: true, onEditTask } });
    await fireEvent.click(getByRole('button', { name: 'edit' }));
    expect(onEditTask).toHaveBeenCalledWith(expect.objectContaining({ task_id: 1 }));
  });

  it('reorders a task via the callback when canManage', async () => {
    const onReorder = vi.fn();
    const { getAllByRole } = render(TaskTree, {
      props: { tasks: [task({ task_id: 1, name: 'A' }), task({ task_id: 2, name: 'B' })], canManage: true, onReorder },
    });
    // first task's down-arrow is enabled; click it
    await fireEvent.click(getAllByRole('button', { name: '▼' })[0]);
    expect(onReorder).toHaveBeenCalledWith(1, 'down');
  });

  it('shows management affordances when canManage is true', () => {
    const { getByRole } = render(TaskTree, { props: { tasks: [task()], canManage: true } });
    expect(getByRole('button', { name: 'edit' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'assign' })).toBeInTheDocument();
    expect(getByRole('button', { name: '▼' })).toBeInTheDocument();
    expect(getByRole('button', { name: '▲' })).toBeInTheDocument();
  });

  it('opens edit/del to everyone but gates cancel/assign/reorder on canManage', () => {
    // A not-started task with no bleps. edit + del are open (any authenticated
    // user); cancel/assign/reorder require per-job can_manage.
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [task({ status: 'pending', has_bleps: false })], canManage: false },
    });
    // edit/del now open
    expect(queryByRole('button', { name: 'edit' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'del' })).toBeInTheDocument();
    // cancel/assign/reorder still manager-only
    expect(queryByRole('button', { name: 'cancel' })).toBeNull();
    expect(queryByRole('button', { name: 'assign' })).toBeNull();
    expect(queryByRole('button', { name: '▼' })).toBeNull();
    expect(queryByRole('button', { name: '▲' })).toBeNull();
    // material/subtask adds still available
    expect(queryByRole('button', { name: '+mat' })).toBeInTheDocument();
    expect(queryByRole('button', { name: '+sub' })).toBeInTheDocument();
  });

  it('shows cancel + assign + reorder when canManage is true (cancellable status)', () => {
    // 'blocked' is cancellable but NON_DELETABLE allows del (only in_progress/complete block del).
    const { getByRole } = render(TaskTree, {
      props: { tasks: [task({ status: 'blocked', has_bleps: false })], canManage: true },
    });
    expect(getByRole('button', { name: 'edit' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'cancel' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'assign' })).toBeInTheDocument();
    expect(getByRole('button', { name: '▼' })).toBeInTheDocument();
    expect(getByRole('button', { name: '▲' })).toBeInTheDocument();
  });

  it('hides del when the task has bleps, even though edit still shows', () => {
    // 'pending' is deletable by status, but has_bleps mirrors the backend no-Bleps rule.
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [task({ status: 'pending', has_bleps: true })], canManage: true },
    });
    expect(queryByRole('button', { name: 'edit' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'del' })).toBeNull();
  });

  it('keeps cancel/assign/reorder hidden when canManage is omitted but edit/del open', () => {
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [task({ status: 'pending', has_bleps: false })] },
    });
    expect(queryByRole('button', { name: 'edit' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'del' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'assign' })).toBeNull();
    expect(queryByRole('button', { name: 'cancel' })).toBeNull();
  });
});
