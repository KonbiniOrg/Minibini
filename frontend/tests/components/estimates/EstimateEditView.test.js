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

  it('ticking a pool row makes every line grow "Add selected here" and the placeholder row appears', async () => {
    const { findByText, findAllByText, container } = render(EstimateEditView, {
      props: baseProps({
        sourcePool: poolWith([AVAILABLE_ATOM]),
        lineItems: [backedLine(), handLine()],
      }),
    });
    await findByText('Sand edges');
    expect(container.textContent).not.toContain('Add selected here');

    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);

    const addHereButtons = await findAllByText('Add selected here');
    expect(addHereButtons).toHaveLength(2);
    expect(container.textContent).toContain('New line from selected');
  });

  it('clicking a line\'s "Add selected here" POSTs add-atoms with the ticked ids', async () => {
    api.post.mockResolvedValue({});
    const { findByText, findAllByText, container } = render(EstimateEditView, {
      props: baseProps({
        sourcePool: poolWith([AVAILABLE_ATOM]),
        lineItems: [backedLine()],
      }),
    });
    await findByText('Sand edges');
    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);

    const [addHereBtn] = await findAllByText('Add selected here');
    await fireEvent.click(addHereBtn);

    expect(api.post).toHaveBeenCalledWith(
      '/api/estimates/7/line-items/1/add-atoms/',
      { atoms: [{ type: 'task', id: 41 }] },
    );
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

  it('offers the next line number as max(line_number)+1, not the line count', async () => {
    const { findByText, container } = render(EstimateEditView, {
      props: baseProps({
        sourcePool: poolWith([AVAILABLE_ATOM]),
        // Two lines, but the higher line_number is 5 (a gap) — length+1
        // would wrongly say "line 3".
        lineItems: [backedLine({ line_number: 1 }), handLine({ line_number: 5 })],
      }),
    });
    await findByText('Sand edges');
    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);
    expect(container.textContent).toContain('line 6');
    expect(container.textContent).not.toContain('line 3');
  });

  it('a 409 on "Add selected here" clears selection, refreshes via onChanged, and shows a clear conflict message', async () => {
    api.post.mockRejectedValueOnce(conflictError());
    const onChanged = vi.fn();
    const { findByText, findAllByText, container } = render(EstimateEditView, {
      props: baseProps({
        sourcePool: poolWith([AVAILABLE_ATOM]),
        lineItems: [backedLine()],
        onChanged,
      }),
    });
    await findByText('Sand edges');
    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);
    const [addHereBtn] = await findAllByText('Add selected here');
    await fireEvent.click(addHereBtn);

    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(get(overlayMessage)?.kind).toBe('error');
    expect(get(overlayMessage)?.text).toMatch(/claimed/i);
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
