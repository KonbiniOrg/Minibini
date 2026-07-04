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

  it('includes fees as rows in the same table and in the grand total', async () => {
    const t = task({}); // task total 2*25 = $50.00
    const onEditFee = vi.fn();
    // fee 4 * 12.50 = $50.00 → grand total 50 + 50 = $100.00
    const fee = { fee_id: 3, description: 'Setup fee', quantity: '4', unit_rate: '12.50' };
    const { getByText, container } = render(TaskTree, {
      props: { tasks: [t], fees: [fee], canManage: true, onEditFee },
    });
    expect(getByText('Setup fee')).toBeInTheDocument();          // fee row present in the same table
    const feeRow = container.querySelector('.fee-row');
    expect(feeRow).not.toBeNull();                               // distinguishable styling
    expect(getByText('$100.00')).toBeInTheDocument();            // fee is in the grand total
    // the fee's own edit affordance calls back with the fee
    await fireEvent.click(feeRow.querySelector('button'));
    expect(onEditFee).toHaveBeenCalledWith(expect.objectContaining({ fee_id: 3 }));
  });

  it('shows the catalog badge for an inventory-item-backed material', () => {
    const t = task({
      materials: [{
        description: 'Steel', quantity: '3', sell_price: '5', units: 'kg',
        consumption_state: 'pending', inventory_item_is_catalog: true,
      }],
    });
    const { container } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(container.querySelector('.inv-badge')).not.toBeNull();
  });

  it('omits the catalog badge for a freeform material', () => {
    const t = task({
      materials: [{
        description: 'Glue', quantity: '1', sell_price: '2', units: 'ea',
        consumption_state: 'pending', inventory_item_is_catalog: false,
      }],
    });
    const { container } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(container.querySelector('.inv-badge')).toBeNull();
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

  it('nests a cost-item expense under its material and lists loose expenses', () => {
    const t = task({
      task_id: 9, name: 'Assemble', materials: [],
    });
    const { getByText } = render(TaskTree, {
      props: {
        tasks: [t],
        jobMaterials: [{ material_id: 50, description: 'Bracket', quantity: '1', sell_price: '0', unit_cost: '4', units: 'ea', consumption_state: 'pending' }],
        expenses: [
          { id: 1, material: 50, description: 'bracket receipt', amount: '4.40' },
          { id: 2, material: null, description: 'FedEx shipping', amount: '40.00' },
        ],
        canManage: true,
      },
    });
    expect(getByText('bracket receipt')).toBeInTheDocument();   // nested under material
    expect(getByText('FedEx shipping')).toBeInTheDocument();    // loose, under "Expenses"
    expect(getByText('Expenses')).toBeInTheDocument();
  });

  it('fires onEditExpense from an expense row', async () => {
    const onEditExpense = vi.fn();
    const { getAllByRole } = render(TaskTree, {
      props: {
        tasks: [],
        expenses: [{ id: 7, material: null, description: 'shipping', amount: '40.00' }],
        onEditExpense,
      },
    });
    // The only edit button present is the expense's.
    await fireEvent.click(getAllByRole('button', { name: 'edit' })[0]);
    expect(onEditExpense).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
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

  it('shows an INVOICED link instead of the status indicator on an invoiced task', () => {
    const t = task({ status: 'complete', invoice: { id: 7, number: 'INV-7' } });
    const { getByRole, queryByText } = render(TaskTree, { props: { tasks: [t] } });
    const link = getByRole('link', { name: 'INVOICED' });
    expect(link.getAttribute('href')).toBe('#/invoices/7');
    // The normal status label ("Complete") is replaced, not shown alongside.
    expect(queryByText('Complete')).toBeNull();
  });

  it('shows the status indicator (no INVOICED link) on an uninvoiced complete task', () => {
    const t = task({ status: 'complete', invoice: null });
    const { queryByRole, getByText } = render(TaskTree, { props: { tasks: [t] } });
    expect(queryByRole('link', { name: 'INVOICED' })).toBeNull();
    expect(getByText('Complete')).toBeInTheDocument();
  });

  it('shows an INVOICED link in the status column of an invoiced material', () => {
    const t = task({
      materials: [{
        material_id: 9, description: 'Steel', quantity: '3', sell_price: '5',
        units: 'kg', consumption_state: 'consumed', invoice: { id: 4, number: 'INV-4' },
      }],
    });
    const { getByRole } = render(TaskTree, { props: { tasks: [t] } });
    const link = getByRole('link', { name: 'INVOICED' });
    expect(link.getAttribute('href')).toBe('#/invoices/4');
  });

  it('offers no restock on a released material (terminal, like consumed)', () => {
    const t = task({
      status: 'pending',
      materials: [{
        material_id: 10, description: 'Acrylic', quantity: '0', sell_price: '5',
        units: 'ea', consumption_state: 'released', released_qty: '7', invoice: null,
      }],
    });
    const { queryByRole } = render(TaskTree, { props: { tasks: [t] } });
    expect(queryByRole('button', { name: 'restock' })).toBeNull();
  });
});
