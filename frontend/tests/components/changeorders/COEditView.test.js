import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import COEditView from '@/components/changeorders/COEditView.svelte';

const CO = {
  change_order_id: 3,
  estimate: 7,
  line_items: [
    { line_item_id: 11, action: 'remove', line_number: 1, target_line_item: 2 },
    {
      line_item_id: 12, action: 'replace', line_number: 2, target_line_item: 3,
      description: 'Widget C v2', qty: '5.00', units: 'ea', price: '30.00',
      accounting_category: 5,
    },
    {
      line_item_id: 13, action: 'add', line_number: 3,
      description: 'Extra Item', qty: '2.00', units: 'ea', price: '60.00',
      accounting_category: 5,
    },
  ],
};

function agreementLine(overrides = {}) {
  return {
    description: 'Widget A', qty: '2.00', units: 'ea', price: '100.00', amount: '200.00',
    accounting_category_id: 5, origin: 'estimate', is_adjustment: false,
    adjustment_service_id: null, percent: null, target_category_ids: [],
    estimate_line_id: 1, co_line_id: null,
    ...overrides,
  };
}

function agreementRow(overrides = {}) {
  const { line: lineOverrides, ...rowOverrides } = overrides;
  return {
    kind: 'agreement',
    line: agreementLine(lineOverrides),
    billed_on: null,
    adjustment_expected_amount: null,
    backing: 'hand',
    backing_total: null,
    ...rowOverrides,
  };
}

const REMOVED_ROW = {
  kind: 'removed',
  original: {
    description: 'Widget B', qty: '1.00', units: 'ea', price: '50.00', amount: '50.00',
    accounting_category_id: 5, is_adjustment: false, estimate_line_id: 2, co_line_id: null,
  },
  co_line_id: 11,
};

const REPLACED_ROW = {
  kind: 'replaced',
  line: {
    description: 'Widget C v2', qty: '5.00', units: 'ea', price: '30.00', amount: '150.00',
    accounting_category_id: 5, is_adjustment: false, percent: null, co_line_id: 12,
  },
  original: {
    description: 'Widget C', qty: '3.00', units: 'ea', price: '25.00', amount: '75.00',
    accounting_category_id: 5, is_adjustment: false, estimate_line_id: 3, co_line_id: null,
  },
  co_line_id: 12,
  co_index: 1,
  backing: 'edited_work',
  backing_total: '75.00',
  sources: [
    {
      source_id: 55, source_type: 'task', source_pk: 9, description: 'Cutting',
      qty: '3.00', units: 'ea', rate: '25.00', computed_amount: '75.00',
      inherited_from_line: 3,
    },
  ],
};

const ADDED_ROW = {
  kind: 'added',
  line: {
    description: 'Extra Item', qty: '2.00', units: 'ea', price: '60.00', amount: '120.00',
    accounting_category_id: 5, is_adjustment: false, co_line_id: 13,
  },
  co_line_id: 13,
  co_index: 2,
  backing: 'hand',
  backing_total: null,
  sources: [],
};

function amendedPayload(rows) {
  return { rows, original_total: '325.00', co_delta: '145.00', revised_total: '470.00' };
}

function baseProps(overrides = {}) {
  return {
    co: CO,
    canEdit: true,
    onChanged: vi.fn(),
    amended: amendedPayload([agreementRow(), REMOVED_ROW, REPLACED_ROW, ADDED_ROW]),
    sourcePool: { atoms: [] },
    categories: [{ id: 5, code: 'GEN', name: 'General' }],
    ...overrides,
  };
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  api.get.mockResolvedValue([]);
  api.post.mockResolvedValue({});
  api.delete.mockResolvedValue({ message: 'ok' });
});

describe('COEditView row kinds', () => {
  it('renders all four row kinds with strikes, CO-authored tints, and CO numbering', async () => {
    const { findByText, container } = render(COEditView, { props: baseProps() });

    // agreement
    await findByText('Widget A');
    // removed: struck original, no CO badge
    expect(await findByText('Widget B')).toBeInTheDocument();
    // replaced: new value + struck original + CO badge
    expect(await findByText('Widget C v2')).toBeInTheDocument();
    expect(await findByText('Widget C')).toBeInTheDocument();
    // added: CO badge
    expect(await findByText('Extra Item')).toBeInTheDocument();

    expect(container.querySelectorAll('tr.co-authored')).toHaveLength(2);
    const badges = Array.from(container.querySelectorAll('.co-badge')).map((b) => b.textContent);
    expect(badges).toEqual(['CO 1', 'CO 2']);

    // struck rows carry the .struck class, parenthesized amount, excluded look
    const struckCells = container.querySelectorAll('td.struck');
    expect(struckCells.length).toBeGreaterThan(0);
    expect(container.textContent).toContain('($50.00)'); // removed original, parenthesized
    expect(container.textContent).toContain('($75.00)'); // replaced original, parenthesized

    // inherited-preview atom row
    expect(await findByText('Cutting')).toBeInTheDocument();
    expect(await findByText(/inherited from line 3/)).toBeInTheDocument();
  });

  it('never renders the word "delete" anywhere', async () => {
    const { queryByText, findByText } = render(COEditView, { props: baseProps() });
    await findByText('Widget A');
    expect(queryByText(/delete/i)).toBeNull();
  });
});

describe('COEditView billed_on gating', () => {
  it('disables both gesture buttons with a "billed on" title and caption when billed_on is set', async () => {
    const { findByText, getByRole } = render(COEditView, {
      props: baseProps({
        amended: amendedPayload([agreementRow({ billed_on: 'INV-9' })]),
      }),
    });
    await findByText('Widget A');

    const removeBtn = getByRole('button', { name: 'Remove via CO' });
    const replaceBtn = getByRole('button', { name: /Replace/ });
    expect(removeBtn).toBeDisabled();
    expect(replaceBtn).toBeDisabled();
    expect(removeBtn).toHaveAttribute('title', 'Billed on INV-9');
    expect(replaceBtn).toHaveAttribute('title', 'Billed on INV-9');
    expect(await findByText(/billed on INV-9/)).toBeInTheDocument();
  });

  it('shows the "recomputes to $X if replaced" caption for a stale adjustment line', async () => {
    const { findByText } = render(COEditView, {
      props: baseProps({
        amended: amendedPayload([
          agreementRow({ line: { is_adjustment: true, percent: '10.00' }, adjustment_expected_amount: '12.34' }),
        ]),
      }),
    });
    expect(await findByText(/recomputes to \$12\.34 if replaced/)).toBeInTheDocument();
  });
});

describe('COEditView Undo / Remove gestures', () => {
  it('Undo on a replaced row DELETEs the CO line', async () => {
    const onChanged = vi.fn();
    const { findByText, getByRole } = render(COEditView, {
      props: baseProps({ amended: amendedPayload([REPLACED_ROW]), onChanged }),
    });
    await findByText('Widget C v2');
    await fireEvent.click(getByRole('button', { name: 'Undo' }));
    expect(api.delete).toHaveBeenCalledWith('/api/change-orders/3/line-items/12/');
    expect(onChanged).toHaveBeenCalled();
  });

  it('Undo on a removed row DELETEs the CO line', async () => {
    const { findByText, getByRole } = render(COEditView, {
      props: baseProps({ amended: amendedPayload([REMOVED_ROW]) }),
    });
    await findByText('Widget B');
    await fireEvent.click(getByRole('button', { name: 'Undo' }));
    expect(api.delete).toHaveBeenCalledWith('/api/change-orders/3/line-items/11/');
  });

  it('Remove on an added row DELETEs the CO line', async () => {
    const { findByText, getByRole } = render(COEditView, {
      props: baseProps({ amended: amendedPayload([ADDED_ROW]) }),
    });
    await findByText('Extra Item');
    await fireEvent.click(getByRole('button', { name: 'Remove' }));
    expect(api.delete).toHaveBeenCalledWith('/api/change-orders/3/line-items/13/');
  });

  it('Remove via CO on an agreement row POSTs a remove line', async () => {
    const { findByText, getByRole } = render(COEditView, { props: baseProps({ amended: amendedPayload([agreementRow()]) }) });
    await findByText('Widget A');
    await fireEvent.click(getByRole('button', { name: 'Remove via CO' }));
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/3/line-items/', {
      action: 'remove', target_line_item: 1,
    });
  });
});

describe('COEditView new-line-from-selected', () => {
  it('ticking a pool row and clicking "Bundle into line…" opens BundleModal seeded from the atom, and Create POSTs overrides', async () => {
    api.post.mockResolvedValue({
      line_item_id: 99, line_number: 4, description: 'Sand edges', qty: '1', units: 'hour', price: '30.00',
    });
    const onChanged = vi.fn();
    const { findByText, findByRole, container } = render(COEditView, {
      props: baseProps({
        onChanged,
        sourcePool: {
          atoms: [{
            type: 'task', id: 41, description: 'Sand edges', qty: '1', rate: '30.00',
            amount: '30.00', units: 'hour', state: 'available',
            claiming_change_order_number: null, claiming_estimate_number: null,
          }],
        },
      }),
    });
    await findByText('Sand edges');
    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);

    const bundleBtn = await findByRole('button', { name: /bundle into line/i });
    await fireEvent.click(bundleBtn);

    const dialog = await findByRole('dialog');
    // Seeded from the single selected atom.
    expect(within(dialog).getByLabelText(/Quantity/)).toHaveValue(1);
    expect(within(dialog).getByLabelText(/Price/)).toHaveValue(30);

    await fireEvent.click(within(dialog).getByRole('button', { name: /create line/i }));

    expect(api.post).toHaveBeenCalledWith(
      '/api/change-orders/3/line-items-from-atoms/',
      {
        atoms: [{ type: 'task', id: 41 }],
        overrides: { description: 'Sand edges', qty: '1', units: 'hour', price: '30.00' },
      },
    );
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it('never shows "Add selected here" on an added row, even with a pool atom ticked', async () => {
    // Task 6: the attach-to-existing-line gesture is retired everywhere
    // (estimate + CO); composing atoms into lines happens only via
    // "New line from selected" / the bundle modal.
    const { findByText, container } = render(COEditView, {
      props: baseProps({
        amended: amendedPayload([ADDED_ROW]),
        sourcePool: {
          atoms: [{
            type: 'task', id: 41, description: 'Sand edges', qty: '1', rate: '30.00',
            amount: '30.00', units: 'hour', state: 'available',
            claiming_change_order_number: null, claiming_estimate_number: null,
          }],
        },
      }),
    });
    await findByText('Sand edges');
    expect(container.textContent).not.toContain('Add selected here');

    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);

    expect(container.textContent).not.toContain('Add selected here');
    expect(container.textContent).toContain('New line from selected');
  });
});

describe('COEditView Replace… gestures', () => {
  it('Replace… on a plain agreement line opens the field-edit variant, prefilled', async () => {
    const { findByText, getByRole, getByLabelText } = render(COEditView, {
      props: baseProps({ amended: amendedPayload([agreementRow()]) }),
    });
    await findByText('Widget A');
    await fireEvent.click(getByRole('button', { name: /Replace/ }));

    expect(await findByText('Replace Line')).toBeInTheDocument();
    expect(getByLabelText(/Description/)).toHaveValue('Widget A');
    expect(getByLabelText(/Quantity/)).toHaveValue(2);
    expect(getByLabelText(/Price/)).toHaveValue(100);
  });

  it('Replace… on an adjustment agreement line opens the percent variant, not qty/units/price', async () => {
    const { findByText, getByRole, getByLabelText, queryByLabelText } = render(COEditView, {
      props: baseProps({
        amended: amendedPayload([
          agreementRow({ line: { is_adjustment: true, percent: '10.00', description: 'Rush 10%' } }),
        ]),
      }),
    });
    await findByText('Rush 10%');
    await fireEvent.click(getByRole('button', { name: /Replace/ }));

    expect(await findByText('Replace Adjustment')).toBeInTheDocument();
    expect(getByLabelText(/Percent/)).toHaveValue(10);
    expect(queryByLabelText(/Quantity/)).toBeNull();
    expect(queryByLabelText(/^Price/)).toBeNull();
  });

  it('does not offer Remove via CO / Replace… when the row has no estimate_line_id (rare CO-origin baseline line)', async () => {
    const { findByText, queryByRole } = render(COEditView, {
      props: baseProps({
        amended: amendedPayload([agreementRow({ line: { estimate_line_id: null } })]),
      }),
    });
    await findByText('Widget A');
    expect(queryByRole('button', { name: 'Remove via CO' })).toBeNull();
    expect(queryByRole('button', { name: /Replace/ })).toBeNull();
  });
});

describe('COEditView agreement-row nested atoms', () => {
  it("renders an agreement row's claimed atoms as read-only child rows", async () => {
    const row = agreementRow({
      backing: 'planned_work',
      backing_total: '200.00',
      sources: [{
        source_id: 71, source_type: 'task', source_pk: 21, description: 'Sanding',
        qty: '2.00', units: 'hour', rate: '100.00', computed_amount: '200.00',
      }],
    });
    const { findByText, container } = render(COEditView, {
      props: baseProps({ amended: amendedPayload([row]) }),
    });
    await findByText('Widget A');

    const childRow = [...container.querySelectorAll('tr.doc-atom-row')]
      .find((tr) => tr.textContent.includes('Sanding'));
    expect(childRow).toBeTruthy();
    // Read-only: no per-atom Remove control — claims move via replace/remove
    // gestures on the line, never atom-by-atom on the agreement.
    expect(childRow.querySelector('button')).toBeNull();
  });
});

describe('COEditView uncovered-work pool filtering', () => {
  const POOL = {
    atoms: [
      {
        type: 'task', id: 41, description: 'Sand edges', qty: '1', rate: '30.00',
        amount: '30.00', units: 'hour', state: 'available',
      },
      {
        // Claimed by THIS CO's own agreement — displays nested under its
        // agreement line above, never as disabled pool noise.
        type: 'task', id: 42, description: 'Covered agreement task', qty: '2',
        rate: '100.00', amount: '200.00', units: 'hour', state: 'claimed_by_other',
        claiming_estimate_id: 7, claiming_estimate_number: 'EST-0001',
      },
      {
        // Claimed by a DIFFERENT estimate — still a real conflict, stays
        // visible as a disabled row.
        type: 'task', id: 43, description: 'Other estimate task', qty: '1',
        rate: '50.00', amount: '50.00', units: 'hour', state: 'claimed_by_other',
        claiming_estimate_id: 8, claiming_estimate_number: 'EST-0002',
      },
      {
        type: 'task', id: 44, description: 'Other CO task', qty: '1',
        rate: '40.00', amount: '40.00', units: 'hour', state: 'claimed_by_other',
        claiming_change_order_id: 9, claiming_change_order_number: 'CO-9',
      },
    ],
  };

  it('hides atoms claimed by this CO\'s own agreement, keeps other claims as disabled rows', async () => {
    const { findByText, queryByText } = render(COEditView, {
      props: baseProps({ sourcePool: POOL }),
    });
    await findByText('Sand edges');
    expect(queryByText('Covered agreement task')).toBeNull();
    await findByText('Other estimate task');
    await findByText(/Claimed by estimate EST-0002/);
    await findByText('Other CO task');
    await findByText(/Claimed by change order CO-9/);
  });
});

describe('COEditView canEdit gating', () => {
  it('hides Add line, all gesture buttons, and uncovered work when canEdit is false', async () => {
    const { findByText, queryByText, queryByRole } = render(COEditView, {
      props: baseProps({
        canEdit: false,
        sourcePool: { atoms: [{ type: 'task', id: 41, description: 'Sand edges', qty: '1', rate: '30.00', amount: '30.00', units: 'hour', state: 'available' }] },
      }),
    });
    await findByText('Widget A');
    expect(queryByText('Add line')).toBeNull();
    expect(queryByRole('button', { name: 'Remove via CO' })).toBeNull();
    expect(queryByRole('button', { name: 'Undo' })).toBeNull();
    expect(queryByText('Sand edges')).toBeNull();
  });
});
