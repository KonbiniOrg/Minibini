import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import EstimateEditView from '@/components/estimates/EstimateEditView.svelte';

const ESTIMATE = { estimate_id: 7, estimate_number: 'EST-7', version: 1, status: 'draft' };

function backedLine(overrides = {}) {
  return {
    line_item_id: 1,
    line_number: 1,
    description: 'Cut parts',
    qty: '2',
    units: 'hour',
    price: '25.00',
    accounting_category: 3,
    is_material: false,
    inventory_item: null,
    service_item: null,
    service_item_detail: null,
    adjustment_service: null,
    adjustment_service_detail: null,
    adjustment_target_categories: [],
    backing: 'planned_work',
    backing_total: '50.00',
    sources: [
      { source_id: 55, source_type: 'task', source_pk: 9, description: 'Cutting task',
        computed_amount: '50.00', qty: '2', units: 'hour', rate: '25.00' },
    ],
    ...overrides,
  };
}

function handLine(overrides = {}) {
  return {
    line_item_id: 2,
    line_number: 2,
    description: 'Hand entry',
    qty: '1',
    units: 'none',
    price: '10.00',
    accounting_category: 3,
    is_material: false,
    inventory_item: null,
    service_item: null,
    service_item_detail: null,
    adjustment_service: null,
    adjustment_service_detail: null,
    adjustment_target_categories: [],
    backing: 'hand',
    backing_total: null,
    sources: [],
    ...overrides,
  };
}

function poolWith(atoms) {
  return { atoms };
}

const AVAILABLE_ATOM = {
  type: 'task', id: 41, description: 'Sand edges', qty: '1', rate: '30.00',
  amount: '30.00', units: 'hour', category_id: null, state: 'available',
  claiming_line_item_id: null, claiming_line_number: null,
  claiming_estimate_id: null, claiming_estimate_number: null,
};

function baseProps(overrides = {}) {
  return {
    estimate: ESTIMATE,
    canEdit: true,
    onChanged: vi.fn(),
    sourcePool: poolWith([]),
    lineItems: [backedLine()],
    categories: [{ id: 3, code: 'LAB', name: 'Labor' }],
    ...overrides,
  };
}

function conflictError() {
  return Object.assign(new Error('Some atoms were claimed by another estimate.'), {
    status: 409,
    data: { detail: 'Some atoms were claimed by another estimate.', code: 'atoms_already_claimed', atom_ids: [41] },
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  clearMessage();
});

describe('EstimateEditView', () => {
  it('renders a backed line with its atom nest and chip, including the atom\'s real qty/rate', async () => {
    const { findByText, container } = render(EstimateEditView, { props: baseProps() });
    await findByText('Cut parts');
    expect(await findByText('Cutting task')).toBeInTheDocument();
    expect(await findByText('planned work')).toBeInTheDocument();
    // The nested atom row's qty/rate come from the source's own fields now
    // (not blanked to '-') — Task 6's serializer addition. Scoped to the
    // row itself since "$25.00"/"$50.00" also appear on the parent line.
    const atomRow = container.querySelector('tr.doc-atom-row');
    expect(atomRow.textContent).toContain('2 hour');
    expect(atomRow.textContent).toContain('$25.00');
  });

  it('ticking a pool row shows the "New line from selected" placeholder row, never a per-line attach gesture', async () => {
    // Task 6: "Add selected here" (attach pool atoms to an existing line) is
    // retired — composing atoms into lines happens only via the bundle
    // modal / "New line from selected", never an in-table attach.
    const { findByText, container } = render(EstimateEditView, {
      props: baseProps({
        sourcePool: poolWith([AVAILABLE_ATOM]),
        lineItems: [backedLine(), handLine()],
      }),
    });
    await findByText('Sand edges');
    expect(container.textContent).not.toContain('Add selected here');

    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);

    expect(container.textContent).not.toContain('Add selected here');
    expect(container.textContent).toContain('New line from selected');
  });

  it('shows "Claimed by estimate EST-N" for an atom claimed_by_other on another estimate', async () => {
    const claimedByEstimate = {
      ...AVAILABLE_ATOM, id: 42, description: 'Weld joints', state: 'claimed_by_other',
      claiming_estimate_id: 8, claiming_estimate_number: 'EST-8',
      claiming_change_order_id: null, claiming_change_order_number: null,
    };
    const { findByText, container } = render(EstimateEditView, {
      props: baseProps({ sourcePool: poolWith([claimedByEstimate]) }),
    });
    await findByText('Weld joints');
    expect(await findByText(/Claimed by estimate EST-8/)).toBeInTheDocument();
    const row = container.querySelector('tr.doc-unselectable-row');
    expect(row).not.toBeNull();
    expect(row.querySelector('input[type="checkbox"]')).toBeDisabled();
  });

  it('shows "Claimed by change order CO-N" (not "Claimed by estimate") for an atom claimed by a CO add line', async () => {
    // Task 7 cross-lens fix: a CO-claimed atom comes back claimed_by_other
    // with claiming_estimate_number null and claiming_change_order_number
    // set — the note must branch on that, not fall into the old
    // "Claimed by estimate " (empty number) text.
    const claimedByCO = {
      ...AVAILABLE_ATOM, id: 43, description: 'Trim it out', state: 'claimed_by_other',
      claiming_estimate_id: null, claiming_estimate_number: null,
      claiming_change_order_id: 5, claiming_change_order_number: 'EST-1-CO2',
    };
    const { findByText, queryByText, container } = render(EstimateEditView, {
      props: baseProps({ sourcePool: poolWith([claimedByCO]) }),
    });
    await findByText('Trim it out');
    expect(await findByText(/Claimed by change order EST-1-CO2/)).toBeInTheDocument();
    expect(queryByText(/Claimed by estimate\s*$/)).not.toBeInTheDocument();
    const row = container.querySelector('tr.doc-unselectable-row');
    expect(row).not.toBeNull();
    expect(row.querySelector('input[type="checkbox"]')).toBeDisabled();
  });

  it('"New line from selected" POSTs line-items-from-atoms then opens the edit modal', async () => {
    api.post.mockResolvedValue({ line_item_id: 99, line_number: 2, description: '', qty: '1', units: 'hour', price: '30.00', sources: [] });
    const { findByRole, findByText, getByText, container } = render(EstimateEditView, {
      props: baseProps({
        sourcePool: poolWith([AVAILABLE_ATOM]),
        lineItems: [backedLine()],
      }),
    });
    await findByText('Sand edges');
    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);

    const createBtn = await findByRole('button', { name: /create line/i });
    await fireEvent.click(createBtn);

    expect(api.post).toHaveBeenCalledWith(
      '/api/estimates/7/line-items-from-atoms/',
      { atoms: [{ type: 'task', id: 41 }] },
    );
    expect(await findByRole('dialog')).toBeInTheDocument();
    getByText('Edit Line Item');
  });

  it('Remove calls the DELETE endpoint (single-phase, no confirm param)', async () => {
    api.delete.mockResolvedValue({ message: 'Line item deleted.' });
    const onChanged = vi.fn();
    const { findAllByRole } = render(EstimateEditView, {
      props: baseProps({ lineItems: [backedLine()], onChanged }),
    });
    // Two "Remove" buttons render: the line's own action, and the nested
    // AtomChildRow's per-source detach action — the line-level one is first.
    const [removeBtn] = await findAllByRole('button', { name: 'Remove' });
    await fireEvent.click(removeBtn);
    expect(api.delete).toHaveBeenCalledWith('/api/estimates/7/line-items/1/');
    expect(api.delete).not.toHaveBeenCalledWith(expect.stringContaining('confirm'));
    expect(onChanged).toHaveBeenCalled();
  });

  it('never renders the word "delete" anywhere', async () => {
    const { queryByText, findByText } = render(EstimateEditView, {
      props: baseProps({
        sourcePool: poolWith([AVAILABLE_ATOM]),
        lineItems: [backedLine(), handLine()],
      }),
    });
    await findByText('Cut parts');
    expect(queryByText(/delete/i)).toBeNull();
  });

  it('does not render Add line / Add Adjustment / uncovered work when canEdit is false', async () => {
    const { findByText, queryByText } = render(EstimateEditView, {
      props: baseProps({ canEdit: false, sourcePool: poolWith([AVAILABLE_ATOM]) }),
    });
    await findByText('Cut parts');
    expect(queryByText('Add line')).toBeNull();
    expect(queryByText('Add Adjustment')).toBeNull();
    expect(queryByText('Sand edges')).toBeNull();
    expect(queryByText('Remove')).toBeNull();
  });

  it('shows the "work totals $X" reference on an edited line', async () => {
    const { findByText } = render(EstimateEditView, {
      props: baseProps({ lineItems: [backedLine({ backing: 'edited', backing_total: '50.00' })] }),
    });
    expect(await findByText(/work totals \$50\.00/)).toBeInTheDocument();
  });

  it('does not render the → Deliverable button when onMakeDeliverable is not wired', async () => {
    const { findByText, queryByText } = render(EstimateEditView, { props: baseProps() });
    await findByText('Cut parts');
    expect(queryByText(/Deliverable/)).toBeNull();
  });

  it('renders the → Deliverable button when onMakeDeliverable is wired', async () => {
    const onMakeDeliverable = vi.fn();
    const { findByText } = render(EstimateEditView, {
      props: baseProps({ onMakeDeliverable }),
    });
    const btn = await findByText(/Deliverable/);
    await fireEvent.click(btn);
    expect(onMakeDeliverable).toHaveBeenCalled();
  });

  it('shows a "needs category" marker on an editable line with no accounting_category', async () => {
    const { findByText } = render(EstimateEditView, {
      props: baseProps({ lineItems: [handLine({ accounting_category: null })] }),
    });
    expect(await findByText('needs category')).toBeInTheDocument();
  });

  it('does not show "needs category" once the line has an accounting_category', async () => {
    const { findByText, queryByText } = render(EstimateEditView, {
      props: baseProps({ lineItems: [handLine({ accounting_category: 3 })] }),
    });
    await findByText('Hand entry');
    expect(queryByText('needs category')).toBeNull();
  });

  it('does not show "needs category" when canEdit is false', async () => {
    const { findByText, queryByText } = render(EstimateEditView, {
      props: baseProps({ canEdit: false, lineItems: [handLine({ accounting_category: null })] }),
    });
    await findByText('Hand entry');
    expect(queryByText('needs category')).toBeNull();
  });

  it('labels the direct-bill action with estimate vocabulary, not the invoice kit default', async () => {
    const { findByText, queryByText } = render(EstimateEditView, {
      props: baseProps({ sourcePool: poolWith([AVAILABLE_ATOM]) }),
    });
    expect(await findByText('Add as its own line')).toBeInTheDocument();
    expect(queryByText('Bill as its own line')).toBeNull();
  });

  it('a 409 on "New line from selected" refreshes via onChanged and shows a clear conflict message', async () => {
    api.post.mockRejectedValueOnce(conflictError());
    const onChanged = vi.fn();
    const { findByRole, findByText, container } = render(EstimateEditView, {
      props: baseProps({
        sourcePool: poolWith([AVAILABLE_ATOM]),
        lineItems: [backedLine()],
        onChanged,
      }),
    });
    await findByText('Sand edges');
    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);
    const createBtn = await findByRole('button', { name: /create line/i });
    await fireEvent.click(createBtn);

    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(get(overlayMessage)?.text).toMatch(/claimed/i);
    // The conflict path must not also open the edit modal (there is no new line).
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });
});

describe('EstimateEditView Make Deliverable (spec §6)', () => {
  const LINKED = [{ id: 9, description: '3 chairs', qty_ordered: '3.00', units: 'ea' }];

  it('renders the button when wired and no deliverable is linked; click calls the handler', async () => {
    const onMakeDeliverable = vi.fn();
    const { findByText, getByRole } = render(EstimateEditView, {
      props: baseProps({ onMakeDeliverable, lineItems: [handLine({ linked_deliverables: [] })] }),
    });
    await findByText('Hand entry');
    await fireEvent.click(getByRole('button', { name: 'Make Deliverable' }));
    expect(onMakeDeliverable).toHaveBeenCalledTimes(1);
  });

  it('suppresses the button on a line that already has a linked deliverable', async () => {
    const { findByText, queryByRole } = render(EstimateEditView, {
      props: baseProps({
        onMakeDeliverable: vi.fn(),
        lineItems: [handLine({ linked_deliverables: LINKED, qty: '3', units: 'ea' })],
      }),
    });
    await findByText('Hand entry');
    expect(queryByRole('button', { name: 'Make Deliverable' })).toBeNull();
  });

  it('shows a passive mismatch caption when the linked deliverable qty/units drift', async () => {
    const { findByText, queryByText, rerender } = render(EstimateEditView, {
      props: baseProps({
        lineItems: [handLine({ linked_deliverables: LINKED, qty: '5', units: 'ea' })],
      }),
    });
    await findByText(/deliverable: 3.00 ea/);
    // In-sync line: no caption.
    await rerender(baseProps({
      lineItems: [handLine({ linked_deliverables: LINKED, qty: '3', units: 'ea' })],
    }));
    expect(queryByText(/deliverable: 3.00 ea/)).toBeNull();
  });

  it('Remove on a linked line opens the choice dialog; "remove both" sends delete_deliverables=true', async () => {
    api.delete.mockResolvedValue({ message: 'ok' });
    const { findByText, getAllByRole, getByRole } = render(EstimateEditView, {
      props: baseProps({
        lineItems: [handLine({ linked_deliverables: LINKED, qty: '3', units: 'ea' })],
      }),
    });
    await findByText('Hand entry');
    const removeBtn = getAllByRole('button', { name: 'Remove' })
      .find((b) => !b.closest('[role="dialog"]'));
    await fireEvent.click(removeBtn);
    await findByText(/Remove the deliverable as well\?/);
    await fireEvent.click(getByRole('button', { name: 'Remove line and deliverable' }));
    expect(api.delete).toHaveBeenCalledWith(
      '/api/estimates/7/line-items/2/?delete_deliverables=true');
  });

  it('"keep deliverable" deletes the line without the param; Cancel deletes nothing', async () => {
    api.delete.mockResolvedValue({ message: 'ok' });
    const { findByText, getAllByRole, getByRole, queryByText } = render(EstimateEditView, {
      props: baseProps({
        lineItems: [handLine({ linked_deliverables: LINKED, qty: '3', units: 'ea' })],
      }),
    });
    await findByText('Hand entry');
    await fireEvent.click(getAllByRole('button', { name: 'Remove' })[0]);
    await findByText(/Remove the deliverable as well\?/);
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(api.delete).not.toHaveBeenCalled();
    expect(queryByText(/Remove the deliverable as well\?/)).toBeNull();

    await fireEvent.click(getAllByRole('button', { name: 'Remove' })[0]);
    await findByText(/Remove the deliverable as well\?/);
    await fireEvent.click(getByRole('button', { name: 'Remove line, keep deliverable' }));
    expect(api.delete).toHaveBeenCalledWith('/api/estimates/7/line-items/2/');
  });

  it('"remove both" fires onDeliverablesChanged; "keep" does not', async () => {
    api.delete.mockResolvedValue({ message: 'ok' });
    const onDeliverablesChanged = vi.fn();
    const { findByText, getAllByRole, getByRole } = render(EstimateEditView, {
      props: baseProps({
        onDeliverablesChanged,
        lineItems: [handLine({ linked_deliverables: LINKED, qty: '3', units: 'ea' })],
      }),
    });
    await findByText('Hand entry');
    await fireEvent.click(getAllByRole('button', { name: 'Remove' })[0]);
    await findByText(/Remove the deliverable as well\?/);
    await fireEvent.click(getByRole('button', { name: 'Remove line, keep deliverable' }));
    await new Promise((r) => setTimeout(r, 0));
    expect(onDeliverablesChanged).not.toHaveBeenCalled();

    await fireEvent.click(getAllByRole('button', { name: 'Remove' })[0]);
    await findByText(/Remove the deliverable as well\?/);
    await fireEvent.click(getByRole('button', { name: 'Remove line and deliverable' }));
    await new Promise((r) => setTimeout(r, 0));
    expect(onDeliverablesChanged).toHaveBeenCalledTimes(1);
  });

  it('an unlinked line removes directly with no dialog', async () => {
    api.delete.mockResolvedValue({ message: 'ok' });
    const { findByText, getAllByRole, queryByText } = render(EstimateEditView, {
      props: baseProps({ lineItems: [handLine({ linked_deliverables: [] })] }),
    });
    await findByText('Hand entry');
    await fireEvent.click(getAllByRole('button', { name: 'Remove' })[0]);
    expect(queryByText(/Remove the deliverable as well\?/)).toBeNull();
    expect(api.delete).toHaveBeenCalledWith('/api/estimates/7/line-items/2/');
  });
});
