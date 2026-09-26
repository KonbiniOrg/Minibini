import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import TaskTree from '@/components/TaskTree.svelte';
import { user } from '@/stores/auth.js';

function task(overrides) {
  return {
    task_id: 1, name: 'Cut', status: 'pending', est_qty: '2', effective_rate: '25',
    computed_charge: '0', est_worker_time: null, unit_label: 'hr', materials: [], ...overrides,
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

  it('renders no Fees group and ignores a stale fees prop in the grand total', () => {
    // Fees are gone (better-fees, 2026-08): a caller still passing a legacy
    // `fees` array must get no Fees section and a tasks+materials-only total.
    const t = task({}); // task total 2*25 = $50.00
    const fee = { fee_id: 3, description: 'Setup fee', quantity: '4', unit_rate: '12.50' };
    const { queryByText, container } = render(TaskTree, {
      props: { tasks: [t], fees: [fee], canManage: true },
    });
    expect(queryByText('Fees')).toBeNull();
    expect(queryByText('Setup fee')).toBeNull();
    expect(container.querySelector('.fee-row')).toBeNull();
    // tasks + materials only — the fee's $50.00 is NOT added ($100.00 nowhere)
    expect(container.querySelector('.grand-total-row').textContent).toContain('$50.00');
    expect(queryByText('$100.00')).toBeNull();
  });

  it('shows material units inline beside the qty (the Units column is gone)', () => {
    // RM 2026-08-06: the task tree dropped its Units and Unit Cost columns;
    // the unit rides beside the quantity like Est Time's "h" suffix.
    const t = task({
      materials: [{ material_id: 9, description: 'Steel', quantity: '3', sell_price: '5',
                    units: 'kg', consumption_state: 'pending' }],
    });
    const { getByText, queryByText } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(getByText('3 kg')).toBeInTheDocument();     // glued to qty
    expect(queryByText('kg', { exact: true })).toBeNull(); // no standalone cell
  });

  it('badges an in-progress task waiting on understocked material', () => {
    const t = task({
      status: 'in_progress',
      materials: [{ description: 'Ply', quantity: '3', sell_price: '5', units: 'sheet',
                    consumption_state: 'pending', inventory_item: 7, qty_on_hand: '1.00' }],
    });
    const { getByText } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(getByText('waiting on materials')).toBeInTheDocument();
  });

  it('no badge when the pending material is in stock, freeform, or the task is not started', () => {
    const inStock = task({
      task_id: 11, name: 'A', status: 'in_progress',
      materials: [{ description: 'Ply', quantity: '3', sell_price: '5', units: 'sheet',
                    consumption_state: 'pending', inventory_item: 7, qty_on_hand: '9.00' }],
    });
    const freeform = task({
      task_id: 12, name: 'B', status: 'in_progress',
      materials: [{ description: 'Finish', quantity: '1', sell_price: '5', units: 'ea',
                    consumption_state: 'pending', inventory_item: null, qty_on_hand: '0' }],
    });
    const notStarted = task({
      task_id: 13, name: 'C', status: 'pending',
      materials: [{ description: 'Ply', quantity: '3', sell_price: '5', units: 'sheet',
                    consumption_state: 'pending', inventory_item: 7, qty_on_hand: '0.00' }],
    });
    const { queryByText } = render(TaskTree, {
      props: { tasks: [inStock, freeform, notStarted], canManage: true },
    });
    expect(queryByText('waiting on materials')).toBeNull();
  });

  it('labels the return action "restock" only when stock is on hand', () => {
    const stocked = task({
      task_id: 21, name: 'S', status: 'in_progress',
      materials: [{ material_id: 1, description: 'Ply', quantity: '2', sell_price: '5', units: 'sheet',
                    consumption_state: 'pending', inventory_item: 7, qty_on_hand: '4.00' }],
    });
    const awaited = task({
      task_id: 22, name: 'W', status: 'in_progress',
      materials: [{ material_id: 2, description: 'Special', quantity: '2', sell_price: '5', units: 'sheet',
                    consumption_state: 'pending', inventory_item: 8, qty_on_hand: '0.00' }],
    });
    const freeform = task({
      task_id: 23, name: 'F', status: 'in_progress',
      materials: [{ material_id: 3, description: 'Finish', quantity: '1', sell_price: '5', units: 'ea',
                    consumption_state: 'pending', inventory_item: null, qty_on_hand: '0' }],
    });
    const { getAllByRole } = render(TaskTree, {
      props: { tasks: [stocked, awaited, freeform], canManage: true, onRestockMaterial: vi.fn() },
    });
    expect(getAllByRole('button', { name: 'restock' })).toHaveLength(1);
    expect(getAllByRole('button', { name: 'release' })).toHaveLength(2);
  });

  it('offers a consume button on task-attached pending materials', () => {
    const t = task({
      status: 'in_progress',
      materials: [{ material_id: 4, description: 'Ply', quantity: '2', sell_price: '5', units: 'sheet',
                    consumption_state: 'pending', inventory_item: 7, qty_on_hand: '4.00' }],
    });
    const { getAllByRole } = render(TaskTree, {
      props: { tasks: [t], canManage: true, onConsumeMaterial: vi.fn() },
    });
    expect(getAllByRole('button', { name: 'mark used' })).toHaveLength(1);
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

  it('shows management affordances when canManage is true and callbacks are wired', () => {
    const { getByRole } = render(TaskTree, {
      props: { tasks: [task()], canManage: true,
               onEditTask: vi.fn(), onReorder: vi.fn() },
    });
    expect(getByRole('button', { name: 'edit' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'assign' })).toBeInTheDocument();
    expect(getByRole('button', { name: '▼' })).toBeInTheDocument();
    expect(getByRole('button', { name: '▲' })).toBeInTheDocument();
  });

  it('opens edit/del/cancel to everyone but gates assign/reorder on canManage', () => {
    // A not-started task with no bleps. edit + del + cancel are open (any
    // authenticated user, C2); assign/reorder require per-job can_manage.
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [task({ status: 'pending', has_bleps: false })], canManage: false,
               onEditTask: vi.fn(), onDeleteTask: vi.fn(), onCancelTask: vi.fn(),
               onAddMaterial: vi.fn(), onReorder: vi.fn() },
    });
    // edit/del/cancel open
    expect(queryByRole('button', { name: 'edit' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'del' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'cancel' })).toBeInTheDocument();
    // assign/reorder still manager-only
    expect(queryByRole('button', { name: 'assign' })).toBeNull();
    expect(queryByRole('button', { name: '▼' })).toBeNull();
    expect(queryByRole('button', { name: '▲' })).toBeNull();
    // material add still available
    expect(queryByRole('button', { name: '+mat' })).toBeInTheDocument();
  });

  it('shows cancel + assign + reorder when canManage is true (cancellable status)', () => {
    // 'blocked' is cancellable but NON_DELETABLE allows del (only in_progress/complete block del).
    const { getByRole } = render(TaskTree, {
      props: { tasks: [task({ status: 'blocked', has_bleps: false })], canManage: true,
               onEditTask: vi.fn(), onCancelTask: vi.fn(), onReorder: vi.fn() },
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
      props: { tasks: [task({ status: 'pending', has_bleps: true })], canManage: true,
               onEditTask: vi.fn(), onDeleteTask: vi.fn() },
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

  it('keeps assign/reorder hidden when canManage is omitted but edit/del open', () => {
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [task({ status: 'pending', has_bleps: false })],
               onEditTask: vi.fn(), onDeleteTask: vi.fn(), onReorder: vi.fn() },
    });
    expect(queryByRole('button', { name: 'edit' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'del' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'assign' })).toBeNull();
    expect(queryByRole('button', { name: '▼' })).toBeNull();
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
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [t], onRestockMaterial: vi.fn() },
    });
    expect(queryByRole('button', { name: 'restock' })).toBeNull();
  });
});

describe('TaskTree — material status vocabulary + fulfillment actions', () => {
  afterEach(() => user.set(null));

  function matTask(mat, over = {}) {
    return task({ status: 'in_progress', materials: [mat], ...over });
  }

  it('renders a status chip on each material row (passive display)', () => {
    const t = matTask({
      material_id: 1, description: 'Steel', quantity: '4', sell_price: '5', units: 'kg',
      consumption_state: 'pending', inventory_item: 7, cost_source: 'entered',
      qty_on_hand: '0', po_line_item_id: null, po_number: null,
    });
    const { getByText } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(getByText('Needed')).toBeInTheDocument();
  });

  it('provisional material → "Needs pricing" chip + Set pricing button (no financial atom needed)', async () => {
    const onEditMaterial = vi.fn();
    const t = matTask({
      material_id: 2, description: 'Widget', quantity: '1', sell_price: '0', units: 'ea',
      consumption_state: 'pending', inventory_item: null, cost_source: null, qty_on_hand: '0',
    });
    const { getByText, getByRole } = render(TaskTree, {
      props: { tasks: [t], canManage: true, onEditMaterial },
    });
    expect(getByText('Needs pricing')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Set pricing' }));
    expect(onEditMaterial).toHaveBeenCalledWith(expect.objectContaining({ material_id: 2 }), expect.anything());
  });

  it('needed material gates the Order button behind can_manage_financials', () => {
    const mat = {
      material_id: 3, description: 'Ply', quantity: '4', sell_price: '5', units: 'sheet',
      consumption_state: 'pending', inventory_item: 7, cost_source: 'entered', qty_on_hand: '0',
      po_line_item_id: null, po_number: null,
    };
    const wired = {
      onOrderMaterial: vi.fn(), onAttachExpense: vi.fn(), onMarkOnHand: vi.fn(),
    };
    // worker (no atom): no Order button, but Attach expense + Mark on-hand remain
    user.set({ id: 1, permissions: [] });
    const worker = render(TaskTree, { props: { tasks: [matTask(mat)], canManage: true, ...wired } });
    expect(worker.queryByRole('button', { name: 'Order' })).toBeNull();
    expect(worker.getByRole('button', { name: 'Attach expense' })).toBeInTheDocument();
    expect(worker.getByRole('button', { name: 'Mark on-hand' })).toBeInTheDocument();
    worker.unmount();
    // financial atom present: Order shows
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    const fin = render(TaskTree, { props: { tasks: [matTask(mat)], canManage: true, ...wired } });
    expect(fin.getByRole('button', { name: 'Order' })).toBeInTheDocument();
  });

  it('renders NO fulfillment or material-op buttons when callbacks are not wired (passive surface)', () => {
    // A surface that wires only onEditMaterial must keep every other
    // material action hidden — never a dead button bound to a no-op
    // default.
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    const t = matTask({
      material_id: 8, description: 'Ply', quantity: '4', sell_price: '5', units: 'sheet',
      consumption_state: 'pending', inventory_item: 7, cost_source: 'entered',
      qty_on_hand: '0', po_line_item_id: null, po_number: null,
    });
    const { getByText, queryByRole } = render(TaskTree, {
      props: { tasks: [t], readonly: false, canManage: true },
    });
    expect(getByText('Needed')).toBeInTheDocument(); // chip still shows (passive)
    for (const name of ['Order', 'Attach expense', 'Mark on-hand', 'Mark received',
                        'Set pricing', 'mark used', 'restock', 'release', 'draw more', 'detach']) {
      expect(queryByRole('button', { name })).toBeNull();
    }
  });

  it('ordered material → the status pill itself is the PO link', () => {
    const t = matTask({
      material_id: 4, description: 'Bar', quantity: '4', sell_price: '5', units: 'ea',
      consumption_state: 'pending', inventory_item: 7, cost_source: 'po', qty_on_hand: '0',
      po_line_item_id: 9, po_id: 42, po_number: 'PO-2026-0042', qty_on_order: '4',
    });
    const { getByRole, queryByRole } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    const pill = getByRole('link', { name: 'Ordered — PO-2026-0042' });
    expect(pill.getAttribute('href')).toBe('#/purchase-orders/42');
    expect(pill.classList.contains('mat-status')).toBe(true);
    // no separate PO link in the actions column any more
    expect(queryByRole('link', { name: 'PO-2026-0042' })).toBeNull();
  });

  it('consume renders only when stock covers (On Hand), never on short rows', () => {
    const shortMat = { material_id: 4, description: 'Bar', quantity: '4', sell_price: '5',
      units: 'ea', consumption_state: 'pending', inventory_item: 7, cost_source: 'entered',
      qty_on_hand: '1' };
    const short = render(TaskTree, {
      props: { tasks: [matTask(shortMat)], canManage: true, onConsumeMaterial: vi.fn() },
    });
    expect(short.queryByRole('button', { name: 'mark used' })).toBeNull();
    const covered = render(TaskTree, {
      props: { tasks: [matTask({ ...shortMat, qty_on_hand: '4' })],
               canManage: true, onConsumeMaterial: vi.fn() },
    });
    expect(covered.queryByRole('button', { name: 'mark used' })).not.toBeNull();
  });

  it('on-hold job hides the plan-edit actions but keeps procurement', () => {
    // Job-level material: no task row, so the only possible "edit" button
    // is the material's own.
    const mat = { material_id: 4, description: '?', quantity: '2', sell_price: '0',
      units: 'ea', consumption_state: 'pending', inventory_item: null, cost_source: null,
      qty_on_hand: '0' };
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [], jobMaterials: [mat], canManage: true, jobOnHold: true,
               onEditMaterial: vi.fn(), onRestockMaterial: vi.fn(),
               onAttachExpense: vi.fn() },
    });
    expect(queryByRole('button', { name: 'Set pricing' })).toBeNull();
    expect(queryByRole('button', { name: 'edit' })).toBeNull();
    expect(queryByRole('button', { name: /restock|release/ })).toBeNull();
    // procurement reality stays available
    expect(queryByRole('button', { name: 'Attach expense' })).not.toBeNull();
  });

  it('needs-pricing rows offer Attach expense (attach establishes)', () => {
    const t = matTask({ material_id: 4, description: '?', quantity: '2', sell_price: '0',
      units: 'ea', consumption_state: 'pending', inventory_item: null, cost_source: null,
      qty_on_hand: '0' });
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [t], canManage: true,
               onEditMaterial: vi.fn(), onAttachExpense: vi.fn() },
    });
    expect(queryByRole('button', { name: 'Set pricing' })).not.toBeNull();
    expect(queryByRole('button', { name: 'Attach expense' })).not.toBeNull();
  });

  it('customer-supplied short → "Awaiting customer" chip + Mark received button', async () => {
    const onMarkOnHand = vi.fn();
    const t = matTask({
      material_id: 5, description: 'Panel', quantity: '4', sell_price: '5', units: 'ea',
      consumption_state: 'pending', inventory_item: 7, cost_source: 'customer_supplied',
      qty_on_hand: '0', po_line_item_id: null, po_number: null,
    });
    const { getByText, getByRole } = render(TaskTree, {
      props: { tasks: [t], canManage: true, onMarkOnHand },
    });
    expect(getByText('Awaiting customer')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Mark received' }));
    expect(onMarkOnHand).toHaveBeenCalledWith(expect.objectContaining({ material_id: 5 }));
  });

  it('customer-supplied material offers no edit button (nothing is editable)', () => {
    // Job-level material so the only possible "edit" button is the material's.
    const mat = { material_id: 5, description: 'Panel', quantity: '4', sell_price: '0',
      units: 'ea', consumption_state: 'pending', inventory_item: 7,
      cost_source: 'customer_supplied', qty_on_hand: '0' };
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [], jobMaterials: [mat], canManage: true,
               onEditMaterial: vi.fn(), onMarkOnHand: vi.fn() },
    });
    expect(queryByRole('button', { name: 'edit' })).toBeNull();
    // receiving still works — it's procurement, not editing
    expect(queryByRole('button', { name: 'Mark received' })).not.toBeNull();
  });

  it('flags an estimate-placeholder cost with a ⚠ warning', () => {
    const t = matTask({
      material_id: 6, description: 'Trim', quantity: '4', sell_price: '5', units: 'ea',
      consumption_state: 'pending', inventory_item: 7, cost_source: 'estimated', qty_on_hand: '0',
    });
    const { getByTitle } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(getByTitle(/cost unconfirmed/i)).toBeInTheDocument();
  });

  it('released material row is struck through and shows no fulfillment actions', () => {
    const t = matTask({
      material_id: 7, description: 'Acrylic', quantity: '0', sell_price: '5', units: 'ea',
      consumption_state: 'released', released_qty: '7', inventory_item: 7, cost_source: 'entered',
      qty_on_hand: '0',
    }, { status: 'pending' });
    const { container, queryByRole } = render(TaskTree, {
      props: {
        tasks: [t], canManage: true,
        onOrderMaterial: vi.fn(), onMarkOnHand: vi.fn(),
        onAttachExpense: vi.fn(), onEditMaterial: vi.fn(),
      },
    });
    expect(container.querySelector('.material-row.released')).not.toBeNull();
    expect(queryByRole('button', { name: 'Order' })).toBeNull();
    expect(queryByRole('button', { name: 'Set pricing' })).toBeNull();
  });
});

describe('TaskTree null-guarded task ops (A3/C2), on-hold gating (B2), can_edit (C1)', () => {
  const wired = () => ({
    onEditTask: vi.fn(), onDeleteTask: vi.fn(), onCancelTask: vi.fn(),
    onAddMaterial: vi.fn(), onReorder: vi.fn(),
  });

  it('renders no task-op buttons when their callbacks are not wired', () => {
    const { queryByText } = render(TaskTree, { props: { tasks: [task()], canManage: true } });
    expect(queryByText('edit')).toBeNull();
    expect(queryByText('del')).toBeNull();
    expect(queryByText('cancel')).toBeNull();
    expect(queryByText('+sub')).toBeNull();
  });

  it('renders the task-op buttons when wired', () => {
    const { getByText } = render(TaskTree, { props: { tasks: [task()], canManage: true, ...wired() } });
    expect(getByText('edit')).toBeInTheDocument();
    expect(getByText('del')).toBeInTheDocument();
    expect(getByText('cancel')).toBeInTheDocument();
    expect(getByText('+mat')).toBeInTheDocument();
  });

  it('offers cancel to non-managers when wired (C2)', async () => {
    const onCancelTask = vi.fn();
    const { getByText } = render(TaskTree, {
      props: { tasks: [task()], canManage: false, onCancelTask },
    });
    await fireEvent.click(getByText('cancel'));
    expect(onCancelTask).toHaveBeenCalledWith(expect.objectContaining({ task_id: 1 }));
  });

  it('renders reorder arrows only when onReorder is wired', () => {
    const two = [task(), task({ task_id: 2, name: 'Sand' })];
    const without = render(TaskTree, { props: { tasks: two, canManage: true } });
    expect(without.queryByText('▲')).toBeNull();
    without.unmount();
    const withReorder = render(TaskTree, {
      props: { tasks: two, canManage: true, onReorder: vi.fn() },
    });
    expect(withReorder.queryAllByText('▲').length).toBeGreaterThan(0);
  });

  it('hides task-op buttons while the job is held but keeps procurement actions (B2)', () => {
    const neededMat = {
      material_id: 5, description: 'Ply', quantity: '3', sell_price: '5',
      units: 'sheet', consumption_state: 'pending', inventory_item: 7,
      qty_on_hand: '1.00',
    };
    const { queryByText, getByText } = render(TaskTree, {
      props: {
        tasks: [task({ materials: [neededMat] })], canManage: true,
        jobOnHold: true, ...wired(),
        onMarkOnHand: vi.fn(), onAttachExpense: vi.fn(),
      },
    });
    expect(queryByText('edit')).toBeNull();
    expect(queryByText('del')).toBeNull();
    expect(queryByText('cancel')).toBeNull();
    expect(queryByText('+sub')).toBeNull();
    expect(queryByText('+mat')).toBeNull();
    // Procurement reality stays available on the held job.
    expect(getByText('Mark on-hand')).toBeInTheDocument();
    expect(getByText('Attach expense')).toBeInTheDocument();
  });

  it('honors per-task can_edit=false for the edit button (C1)', () => {
    const locked = task({ status: 'in_progress', can_edit: false });
    const { queryByText } = render(TaskTree, {
      props: { tasks: [locked], canManage: false, onEditTask: vi.fn() },
    });
    expect(queryByText('edit')).toBeNull();
  });

  it('shows edit when can_edit is true or absent', () => {
    const open = task({ status: 'in_progress', can_edit: true });
    const { getByText } = render(TaskTree, {
      props: { tasks: [open], canManage: false, onEditTask: vi.fn() },
    });
    expect(getByText('edit')).toBeInTheDocument();
  });
});

describe('TaskTree — expense delete/reject', () => {
  afterEach(() => user.set(null));

  function financialUser() {
    user.set({ id: 1, permissions: ['can_manage_financials'] });
  }

  it('offers delete and reject on a personal/submitted expense when wired and permitted', async () => {
    financialUser();
    const onDeleteExpense = vi.fn();
    const onRejectExpense = vi.fn();
    const exp = { id: 7, material: null, description: 'shipping', amount: '40.00',
                  payment_method: 'personal', status: 'submitted' };
    const { getByRole } = render(TaskTree, {
      props: { tasks: [], expenses: [exp], onDeleteExpense, onRejectExpense },
    });
    await fireEvent.click(getByRole('button', { name: 'delete' }));
    expect(onDeleteExpense).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
    await fireEvent.click(getByRole('button', { name: 'reject' }));
    expect(onRejectExpense).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
  });

  it('hides reject on a company-paid expense (delete still offered)', () => {
    financialUser();
    const exp = { id: 8, material: null, description: 'lumber run', amount: '90.00',
                  payment_method: 'company', status: 'submitted' };
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [], expenses: [exp], onDeleteExpense: vi.fn(), onRejectExpense: vi.fn() },
    });
    expect(queryByRole('button', { name: 'reject' })).toBeNull();
    expect(queryByRole('button', { name: 'delete' })).toBeInTheDocument();
  });

  it('hides reject on an already-reimbursed expense', () => {
    financialUser();
    const exp = { id: 9, material: null, description: 'gas', amount: '20.00',
                  payment_method: 'personal', status: 'reimbursed' };
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [], expenses: [exp], onDeleteExpense: vi.fn(), onRejectExpense: vi.fn() },
    });
    expect(queryByRole('button', { name: 'reject' })).toBeNull();
  });

  it('hides both buttons without can_manage_financials, even when wired', () => {
    user.set({ id: 1, permissions: [] });
    const exp = { id: 10, material: null, description: 'shipping', amount: '40.00',
                  payment_method: 'personal', status: 'submitted' };
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [], expenses: [exp], onDeleteExpense: vi.fn(), onRejectExpense: vi.fn() },
    });
    expect(queryByRole('button', { name: 'delete' })).toBeNull();
    expect(queryByRole('button', { name: 'reject' })).toBeNull();
  });

  it('hides both buttons when their callbacks are not wired (passive surface)', () => {
    financialUser();
    const exp = { id: 11, material: null, description: 'shipping', amount: '40.00',
                  payment_method: 'personal', status: 'submitted' };
    const { queryByRole } = render(TaskTree, {
      props: { tasks: [], expenses: [exp] },
    });
    expect(queryByRole('button', { name: 'delete' })).toBeNull();
    expect(queryByRole('button', { name: 'reject' })).toBeNull();
  });

  it('an invoiced expense locks the whole row — no edit/delete/reject', () => {
    financialUser();
    const exp = { id: 12, material: null, description: 'shipping', amount: '40.00',
                  payment_method: 'personal', status: 'submitted',
                  invoice: { id: 4, number: 'INV-4' } };
    const { getByText, queryByRole } = render(TaskTree, {
      props: { tasks: [], expenses: [exp], onEditExpense: vi.fn(),
               onDeleteExpense: vi.fn(), onRejectExpense: vi.fn() },
    });
    expect(getByText('billed — locked')).toBeInTheDocument();
    expect(queryByRole('button', { name: 'edit' })).toBeNull();
    expect(queryByRole('button', { name: 'delete' })).toBeNull();
    expect(queryByRole('button', { name: 'reject' })).toBeNull();
  });
});

describe('TaskTree task rows are one shared fragment (TaskRow)', () => {
  it('badges a task waiting on understocked material', () => {
    const t = task({
      task_id: 22, name: 'Starving task', status: 'in_progress',
      est_qty: '1', effective_rate: '10', computed_charge: '0',
      materials: [{ description: 'Ply', quantity: '3', sell_price: '5',
                    units: 'sheet', consumption_state: 'pending',
                    inventory_item: 7, qty_on_hand: '1.00' }],
    });
    const { queryAllByText } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(queryAllByText('waiting on materials').length).toBe(1);
  });
});

describe('TaskRow Est Qty on hour-unit tasks', () => {
  // Hour-unit tasks show Est Qty like every other unit, even though it
  // restates Est Time (backend pair-fills them) — the old
  // duplicate-suppression '-' read as missing data (RM 2026-08-06).
  function estQtyCell(container) {
    const row = container.querySelector('tbody tr.task-row');
    return row.querySelectorAll('td')[5];
  }

  it('shows Est Qty even when it duplicates est_worker_time on an hour-unit scheme', () => {
    const t = task({ est_worker_time: '2:00:00', est_qty: '2', unit_label: 'hour' });
    const { container } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(estQtyCell(container).textContent.trim()).toBe('2 hour');
  });

  it('shows Est Qty when it diverges from est_worker_time (legacy row)', () => {
    const t = task({ est_worker_time: '2:00:00', est_qty: '3', unit_label: 'hour' });
    const { container } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(estQtyCell(container).textContent.trim()).toBe('3 hour');
  });

  it('shows Est Qty normally for a non-hour-unit scheme', () => {
    const t = task({ est_worker_time: null, est_qty: '5', unit_label: 'pcs' });
    const { container } = render(TaskTree, { props: { tasks: [t], canManage: true } });
    expect(estQtyCell(container).textContent.trim()).toBe('5 pcs');
  });
});
