import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import EstimateEditView from '@/components/estimates/EstimateEditView.svelte';

const ESTIMATE = { estimate_id: 7, estimate_number: 'EST-7', version: 1, status: 'draft', job: 9 };

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
    // Server-computed (EstimateLineItemSerializer.needs_work_decision) —
    // a sourced line is always answered.
    needs_work_decision: false,
    work_declined: false,
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
    work_declined: false,
    // Server-computed (EstimateLineItemSerializer.needs_work_decision) —
    // a bare, unanswered, undeclined plain hand line needs a decision by
    // default; individual tests override this to mock other server-side
    // exclusions (deposit/adjustment/catalog/declined) instead of
    // re-deriving them client-side.
    needs_work_decision: true,
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
  // WorkItemForm (embedded for the mint modal, Task 7) fetches rate schemes
  // on mount regardless of whether its own `open` prop is true — give it a
  // harmless default so tests that never open the mint modal don't see an
  // unhandled-shape response.
  api.get.mockResolvedValue({ results: [] });
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

  it('"Bundle into line…" opens BundleModal seeded from the atom, and Create POSTs overrides + refreshes', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour', 'ea']);
      return Promise.resolve({ results: [] });
    });
    api.post.mockResolvedValue({ line_item_id: 99, line_number: 2, description: 'Sand edges', qty: '1', units: 'hour', price: '30.00', sources: [] });
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

    const bundleBtn = await findByRole('button', { name: /bundle into line/i });
    await fireEvent.click(bundleBtn);

    const dialog = await findByRole('dialog');
    // Seeded from the single selected atom (AVAILABLE_ATOM: qty=1, rate=$30, hour).
    expect(within(dialog).getByLabelText(/Quantity/)).toHaveValue(1);
    expect(within(dialog).getByLabelText(/Price/)).toHaveValue(30);

    await fireEvent.click(within(dialog).getByRole('button', { name: /create line/i }));

    expect(api.post).toHaveBeenCalledWith(
      '/api/estimates/7/line-items-from-atoms/',
      {
        atoms: [{ type: 'task', id: 41 }],
        overrides: { description: 'Sand edges', qty: '1', units: 'hour', price: '30.00' },
      },
    );
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    // The bundle modal closes on success — no lingering dialog, no separate
    // edit-modal follow-up (the bundle modal IS the authoring step).
    expect(container.querySelector('[role="dialog"]')).toBeNull();
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

  it('a 409 on the bundle modal\'s Create refreshes via onChanged and shows a clear conflict message', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/settings/units/') return Promise.resolve(['none', 'hour', 'ea']);
      return Promise.resolve({ results: [] });
    });
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
    await fireEvent.click(await findByRole('button', { name: /bundle into line/i }));
    const dialog = await findByRole('dialog');
    await fireEvent.click(within(dialog).getByRole('button', { name: /create line/i }));

    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(get(overlayMessage)?.text).toMatch(/claimed/i);
    // The conflict path closes the bundle modal (there is no new line).
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

describe('EstimateEditView mint / decline / checklist (Task 7)', () => {
  const ACCEPTED = { ...ESTIMATE, status: 'accepted' };
  const DEPOSIT_CATEGORY = { id: 5, code: 'DEP', name: 'Customer Deposits', is_deposit: true };

  it('shows "Generate work…" and "No work needed" on an unanswered plain hand line when canMint', async () => {
    const { findByRole } = render(EstimateEditView, {
      props: baseProps({ estimate: ACCEPTED, canMint: true, canEdit: false, lineItems: [handLine()] }),
    });
    expect(await findByRole('button', { name: 'Generate work…' })).toBeInTheDocument();
    expect(await findByRole('button', { name: 'No work needed' })).toBeInTheDocument();
  });

  it('hides mint buttons when canMint is false, even on an unanswered plain hand line', async () => {
    const { findByText, queryByRole } = render(EstimateEditView, {
      props: baseProps({ estimate: ACCEPTED, canMint: false, canEdit: false, lineItems: [handLine()] }),
    });
    await findByText('Hand entry');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
    expect(queryByRole('button', { name: 'No work needed' })).toBeNull();
  });

  it('hides mint buttons on a backed line (has sources) even when canMint', async () => {
    const { findByText, queryByRole } = render(EstimateEditView, {
      props: baseProps({ estimate: ACCEPTED, canMint: true, canEdit: false, lineItems: [backedLine()] }),
    });
    await findByText('Cut parts');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
  });

  it('hides mint buttons on an adjustment line even when canMint (server says needs_work_decision: false)', async () => {
    const { findByText, queryByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [handLine({
          adjustment_service: 1,
          adjustment_service_detail: { name: 'Rush', rate: '15', algorithm: 'percentage' },
          needs_work_decision: false,
        })],
      }),
    });
    await findByText('Hand entry');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
  });

  it('hides mint buttons on a deposit line even when canMint (server says needs_work_decision: false)', async () => {
    const { findByText, queryByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        categories: [DEPOSIT_CATEGORY],
        lineItems: [handLine({ accounting_category: 5, needs_work_decision: false })],
      }),
    });
    await findByText('Hand entry');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
  });

  it('hides mint buttons on a catalog-identity line (service_item set) even when canMint (server says needs_work_decision: false)', async () => {
    const { findByText, queryByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [handLine({ service_item: 9, sources: [], needs_work_decision: false })],
      }),
    });
    await findByText('Hand entry');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
  });

  it('hides mint buttons on a catalog-identity line (is_material) even when canMint (server says needs_work_decision: false)', async () => {
    const { findByText, queryByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [handLine({ is_material: true, sources: [], needs_work_decision: false })],
      }),
    });
    await findByText('Hand entry');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
  });

  it('trusts li.needs_work_decision even when it disagrees with the line\'s other fields — no client-side re-derivation', async () => {
    // A line shaped like a catalog line (service_item set) but the server
    // says it still needs a decision: the button must show. The predicate
    // lives server-side now (EstimateLineItemSerializer); the component
    // must not re-derive "catalog identity -> hide" itself.
    const { findByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [handLine({ service_item: 9, sources: [], needs_work_decision: true })],
      }),
    });
    expect(await findByRole('button', { name: 'Generate work…' })).toBeInTheDocument();
  });

  it('declined lines show the "no work needed" caption and an Undo button instead of mint buttons', async () => {
    const { findByText, queryByRole, findByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [handLine({ work_declined: true, needs_work_decision: false })],
      }),
    });
    expect(await findByText('no work needed')).toBeInTheDocument();
    expect(await findByRole('button', { name: 'Undo' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
    expect(queryByRole('button', { name: 'No work needed' })).toBeNull();
  });

  it('declined-line caption shows to ALL viewers, not just canMint — Undo stays manage-gated', async () => {
    // canEdit true (so the Actions column renders at all) but canMint
    // false (the checklist-management gate): the caption is informational
    // for anyone who can see the row, same as "needs category"; only the
    // reversing action (Undo) requires canMint.
    const { findByText, queryByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: false, canEdit: true,
        lineItems: [handLine({ work_declined: true, needs_work_decision: false })],
      }),
    });
    expect(await findByText('no work needed')).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Undo' })).toBeNull();
  });

  it('a draft estimate never shows mint affordances or the banner, even if canMint were mistakenly true', async () => {
    const draft = { ...ESTIMATE, status: 'draft' };
    const { findByText, queryByRole, queryByText } = render(EstimateEditView, {
      props: baseProps({ estimate: draft, canMint: true, lineItems: [handLine()] }),
    });
    await findByText('Hand entry');
    expect(queryByText(/need a work decision/)).toBeNull();
    // The mint buttons themselves are legitimately gated on canMint alone
    // (matching the canEdit precedent — the caller is trusted), so this
    // pins the banner's independent estimate.status check specifically.
    void queryByRole;
  });

  it('an open (submitted) estimate shows no mint affordances and no banner', async () => {
    const open = { ...ESTIMATE, status: 'open' };
    const { findByText, queryByRole, queryByText } = render(EstimateEditView, {
      props: baseProps({ estimate: open, canMint: false, canEdit: false, lineItems: [handLine()] }),
    });
    await findByText('Hand entry');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
    expect(queryByText(/need a work decision/)).toBeNull();
  });

  it('"Generate work…" opens WorkItemForm mirror-seeded (presetName/presetQty)', async () => {
    const { findByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [handLine({ line_item_id: 21, description: 'Weld bracket', qty: '4' })],
      }),
    });
    const btn = await findByRole('button', { name: 'Generate work…' });
    await fireEvent.click(btn);
    const dialog = await findByRole('dialog');
    expect(within(dialog).getByLabelText(/Name/)).toHaveValue('Weld bracket');
  });

  it('"Generate work…" mints with claim_estimate_line bound to the line on save', async () => {
    api.post.mockImplementation((url) => {
      if (url === '/api/rate-schemes/?task_applicable=true') return Promise.resolve({ results: [] });
      return Promise.resolve({});
    });
    const RATE_SCHEME = { rate_scheme_id: 1, name: 'Hourly', unit_label: 'hour', rate: '25', modifiers: [] };
    api.get.mockImplementation((url) => {
      if (url === '/api/rate-schemes/?task_applicable=true') return Promise.resolve({ results: [RATE_SCHEME] });
      return Promise.resolve({ results: [] });
    });
    const { findByRole, findByLabelText } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [handLine({ line_item_id: 21, description: 'Weld bracket', qty: '4' })],
      }),
    });
    await fireEvent.click(await findByRole('button', { name: 'Generate work…' }));
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.click(await findByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/9/tasks/', expect.objectContaining({
      claim_estimate_line: 21,
    }));
  });

  it('"Generate work…" onSaved refreshes the doc and pings the job (auto-release may have fired)', async () => {
    const RATE_SCHEME = { rate_scheme_id: 1, name: 'Hourly', unit_label: 'hour', rate: '25', modifiers: [] };
    api.get.mockImplementation((url) => {
      if (url === '/api/rate-schemes/?task_applicable=true') return Promise.resolve({ results: [RATE_SCHEME] });
      return Promise.resolve({ results: [] });
    });
    api.post.mockResolvedValue({});
    const onChanged = vi.fn();
    const onWorkDecisionChanged = vi.fn();
    const { findByRole, findByLabelText } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false, onChanged, onWorkDecisionChanged,
        lineItems: [handLine({ line_item_id: 21 })],
      }),
    });
    await fireEvent.click(await findByRole('button', { name: 'Generate work…' }));
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.click(await findByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(onWorkDecisionChanged).toHaveBeenCalled();
  });

  it('"No work needed" PATCHes work_declined=true with no confirm, then refreshes doc and job', async () => {
    api.patch.mockResolvedValue({});
    const onChanged = vi.fn();
    const onWorkDecisionChanged = vi.fn();
    vi.spyOn(window, 'confirm');
    const { findByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false, onChanged, onWorkDecisionChanged,
        lineItems: [handLine({ line_item_id: 21 })],
      }),
    });
    await fireEvent.click(await findByRole('button', { name: 'No work needed' }));
    expect(window.confirm).not.toHaveBeenCalled();
    expect(api.patch).toHaveBeenCalledWith('/api/estimates/7/line-items/21/', { work_declined: true });
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(onWorkDecisionChanged).toHaveBeenCalled();
  });

  it('Undo PATCHes work_declined=false, then refreshes doc and job', async () => {
    api.patch.mockResolvedValue({});
    const onChanged = vi.fn();
    const onWorkDecisionChanged = vi.fn();
    const { findByRole } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false, onChanged, onWorkDecisionChanged,
        lineItems: [handLine({ line_item_id: 21, work_declined: true, needs_work_decision: false })],
      }),
    });
    await fireEvent.click(await findByRole('button', { name: 'Undo' }));
    expect(api.patch).toHaveBeenCalledWith('/api/estimates/7/line-items/21/', { work_declined: false });
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(onWorkDecisionChanged).toHaveBeenCalled();
  });

  it('shows the checklist banner with the correct unanswered count on an accepted estimate', async () => {
    const { findByText } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [handLine({ line_item_id: 21 }), handLine({ line_item_id: 22, description: 'Second' }), backedLine()],
      }),
    });
    expect(await findByText(
      '2 line(s) need a work decision — the job starts automatically when all are answered.'
    )).toBeInTheDocument();
  });

  it('hides the checklist banner when every line is answered', async () => {
    const { findByText, queryByText } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [backedLine(), handLine({ work_declined: true, needs_work_decision: false })],
      }),
    });
    await findByText('Cut parts');
    expect(queryByText(/need a work decision/)).toBeNull();
  });

  it('banner text promises auto-release only while the job is still approved — not once it\'s already in_progress', async () => {
    // Finding 5a (final review): timeslip-start (or any other trigger) can
    // release the job to in_progress out from under an unfinished
    // checklist — the banner must not keep promising an automatic release
    // that already happened.
    const { findByText, queryByText } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false, jobStatus: 'in_progress',
        lineItems: [handLine({ line_item_id: 21 })],
      }),
    });
    expect(await findByText('1 line(s) still need a work decision.')).toBeInTheDocument();
    expect(queryByText(/starts automatically/)).toBeNull();
  });

  it('banner keeps the auto-release promise while the job is still approved', async () => {
    const { findByText } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false, jobStatus: 'approved',
        lineItems: [handLine({ line_item_id: 21 })],
      }),
    });
    expect(await findByText(
      '1 line(s) need a work decision — the job starts automatically when all are answered.'
    )).toBeInTheDocument();
  });

  it('Actions column (th + td) renders when canMint is true even though canEdit and onMakeDeliverable are both false', async () => {
    const { findByRole } = render(EstimateEditView, {
      props: baseProps({ estimate: ACCEPTED, canMint: true, canEdit: false, lineItems: [handLine()] }),
    });
    const table = await findByRole('table');
    expect(within(table).getByText('Actions')).toBeInTheDocument();
  });

  it('AtomCaptionRow colspan integrity: grows by 1 when canMint is true, even with canEdit/onMakeDeliverable both false', async () => {
    const { container, findByText } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [backedLine()], // has sources -> AtomCaptionRow renders
      }),
    });
    await findByText('Cut parts');
    const captionCell = container.querySelector('tr.doc-atom-caption td[colspan]');
    expect(captionCell).not.toBeNull();
    expect(captionCell.getAttribute('colspan')).toBe('6');
  });
});
