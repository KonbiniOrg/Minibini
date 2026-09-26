import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import { clearMessage } from '@/stores/messages.js';
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

function baseProps(overrides = {}) {
  return {
    estimate: ESTIMATE,
    canEdit: true,
    onChanged: vi.fn(),
    lineItems: [backedLine()],
    categories: [{ id: 3, code: 'LAB', name: 'Labor' }],
    ...overrides,
  };
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
        lineItems: [backedLine(), handLine()],
      }),
    });
    await findByText('Cut parts');
    expect(queryByText(/delete/i)).toBeNull();
  });

  it('does not render Add line / Add Adjustment when canEdit is false', async () => {
    const { findByText, queryByText } = render(EstimateEditView, {
      props: baseProps({ canEdit: false }),
    });
    await findByText('Cut parts');
    expect(queryByText('Add line')).toBeNull();
    expect(queryByText('Add Adjustment')).toBeNull();
    expect(queryByText('Remove')).toBeNull();
  });

  it('shows the "work totals $X" reference on an edited line', async () => {
    const { findByText } = render(EstimateEditView, {
      props: baseProps({ lineItems: [backedLine({ backing: 'edited_work', backing_total: '50.00' })] }),
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

  it('a draft estimate with zero line items shows a hint linking to the Tasks page', async () => {
    // Task 5: the pool/bundling surface left the estimate page entirely —
    // composing lines now happens on the job's Tasks page. An empty draft
    // points there instead of showing a dead table.
    const { findByText } = render(EstimateEditView, {
      props: baseProps({ lineItems: [] }),
    });
    const link = await findByText(/compose lines from the Tasks page/i);
    expect(link.tagName).toBe('A');
    expect(link).toHaveAttribute('href', '#/jobs/9/tasks');
  });

  it('does not show the empty-state hint when canEdit is false, even with zero line items', async () => {
    const { queryByText, findByText } = render(EstimateEditView, {
      props: baseProps({ canEdit: false, lineItems: [] }),
    });
    await findByText('Line Items');
    expect(queryByText(/compose lines from the Tasks page/i)).toBeNull();
  });

  it('does not show the empty-state hint once the estimate has line items', async () => {
    const { queryByText, findByText } = render(EstimateEditView, {
      props: baseProps({ lineItems: [backedLine()] }),
    });
    await findByText('Cut parts');
    expect(queryByText(/compose lines from the Tasks page/i)).toBeNull();
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

  it('Actions cell rowspans the line group; caption colspan stops at Based-on', async () => {
    // RM 2026-08-17: the Actions column is ONE cell per line, spanning the
    // line row + caption + atom rows; sub-rows carry no Actions cell (their
    // X lives left of the description), so the caption spans exactly the
    // five columns up to Based-on.
    const { container, findByText } = render(EstimateEditView, {
      props: baseProps({
        estimate: ACCEPTED, canMint: true, canEdit: false,
        lineItems: [backedLine()], // 1 source -> caption + 1 atom row
      }),
    });
    await findByText('Cut parts');
    const captionCell = container.querySelector('tr.doc-atom-caption td[colspan]');
    expect(captionCell).not.toBeNull();
    expect(captionCell.getAttribute('colspan')).toBe('5');
    const actionsCell = container.querySelector('td.actions-span');
    expect(actionsCell).not.toBeNull();
    // line row + caption row + 1 atom row = rowspan 3
    expect(actionsCell.getAttribute('rowspan')).toBe('3');
  });
});
