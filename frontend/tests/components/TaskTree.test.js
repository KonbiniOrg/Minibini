import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import TaskTree from '@/components/TaskTree.svelte';
import { user } from '@/stores/auth.js';

function task(overrides) {
  return {
    task_id: 1, name: 'Cut', status: 'pending', est_qty: '2', effective_rate: '25',
    computed_charge: '0', est_worker_time: null, scheme_unit_label: 'hr', materials: [], ...overrides,
  };
}

const MANAGER = { id: 1, permissions: ['can_manage_jobs'] };
const WORKER = { id: 2, permissions: [] };

beforeEach(() => {
  user.set(MANAGER);
});

describe('TaskTree', () => {
  it('renders tasks, materials, and a grand total', () => {
    const t = task({
      materials: [{ description: 'Steel', quantity: '3', sell_price: '5', units: 'kg', consumption_state: 'pending' }],
    });
    // task total 2*25 = $50.00, material 3*5 = $15.00, grand = $65.00
    const { getByText } = render(TaskTree, { props: { tasks: [t] } });
    expect(getByText('Cut')).toBeInTheDocument();
    expect(getByText('Steel')).toBeInTheDocument();
    expect(getByText('$65.00')).toBeInTheDocument();
  });

  it('fires the edit callback (manager)', async () => {
    const onEditTask = vi.fn();
    const { getByRole } = render(TaskTree, { props: { tasks: [task()], onEditTask } });
    await fireEvent.click(getByRole('button', { name: 'edit' }));
    expect(onEditTask).toHaveBeenCalledWith(expect.objectContaining({ task_id: 1 }));
  });

  it('reorders a task via the callback (manager)', async () => {
    const onReorder = vi.fn();
    const { getAllByRole } = render(TaskTree, {
      props: { tasks: [task({ task_id: 1, name: 'A' }), task({ task_id: 2, name: 'B' })], onReorder },
    });
    // first task's down-arrow is enabled; click it
    await fireEvent.click(getAllByRole('button', { name: '▼' })[0]);
    expect(onReorder).toHaveBeenCalledWith(1, 'down');
  });

  it('hides task-management actions from a non-manager but keeps material/subtask adds', () => {
    user.set(WORKER);
    const { queryByRole } = render(TaskTree, { props: { tasks: [task()] } });
    // task-management → requires can_manage_jobs
    expect(queryByRole('button', { name: 'edit' })).toBeNull();
    expect(queryByRole('button', { name: 'del' })).toBeNull();
    expect(queryByRole('button', { name: 'assign' })).toBeNull();
    expect(queryByRole('button', { name: '▼' })).toBeNull();
    expect(queryByRole('button', { name: '▲' })).toBeNull();
    // shop-floor / worker lifecycle actions → IsAuthenticated, still available
    expect(queryByRole('button', { name: 'cancel' })).toBeInTheDocument();
    expect(queryByRole('button', { name: '+mat' })).toBeInTheDocument();
    expect(queryByRole('button', { name: '+sub' })).toBeInTheDocument();
  });
});
