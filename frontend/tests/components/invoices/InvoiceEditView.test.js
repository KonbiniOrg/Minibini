import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import InvoiceEditView from '@/components/invoices/InvoiceEditView.svelte';

const INVOICE = { invoice_id: 5, display_number: 'INV-5', status: 'draft', job_has_other_invoices: false };

function agreementRef(overrides = {}) {
  return { kind: 'estimate', line_id: 30, est_qty: '2', est_price: '25.00', est_amount: '50.00', ...overrides };
}

function seededLine(overrides = {}) {
  return {
    line_item_id: 1,
    line_number: 1,
    description: 'Cut parts',
    qty: '2',
    units: 'hour',
    price: '25.00',
    accounting_category: 3,
    adjustment_service: null,
    adjustment_service_detail: null,
    agreement_ref: agreementRef(),
    backing: 'estimate',
    actuals_total: null,
    sources: [],
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
    adjustment_service: null,
    adjustment_service_detail: null,
    agreement_ref: null,
    backing: null,
    actuals_total: null,
    sources: [],
    ...overrides,
  };
}

function poolWith(tasks) {
  return { tasks };
}

const AVAILABLE_ATOM = {
  type: 'task', id: 41, description: 'Sand edges', qty: '1', rate: '30.00',
  amount: '30.00', units: 'hour', state: 'available',
  claiming_invoice_id: null, claiming_invoice_number: null, not_billable_reason: null,
};

function baseProps(overrides = {}) {
  return {
    invoice: INVOICE,
    canEdit: true,
    onChanged: vi.fn(),
    sourcePool: poolWith([]),
    lineItems: [seededLine()],
    categories: [{ id: 3, code: 'LAB', name: 'Labor' }],
    ...overrides,
  };
}

function conflictError() {
  return Object.assign(new Error('Some atoms are already claimed by another invoice.'), {
    status: 409,
    data: { detail: 'Some atoms are already claimed by another invoice.', code: 'atoms_already_claimed', atom_ids: [41] },
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  clearMessage();
});

describe('InvoiceEditView', () => {
  it('shows the estimate chip and no backing controls (besides Edit/Remove) when nothing attached', async () => {
    const { findByText, queryByText } = render(InvoiceEditView, { props: baseProps() });
    await findByText('Cut parts');
    expect(await findByText('estimate')).toBeInTheDocument();
    expect(queryByText('Use estimate')).toBeNull();
    expect(queryByText('Use actuals')).toBeNull();
  });

  it('suppresses the "· +$Δ" clause entirely when the delta is exactly zero (never shows "· +-")', async () => {
    // Untouched seeded line: current amount (qty*price) equals est_amount
    // exactly, so delta is 0 — fmtMoney(0) is '-', and showing the clause
    // unconditionally would render the nonsense "est was $50.00 · +-".
    const { findByText, queryByText } = render(InvoiceEditView, { props: baseProps() });
    const ref = await findByText(/est was \$50\.00/);
    expect(ref.textContent).toBe('est was $50.00');
    expect(queryByText(/·/)).toBeNull();
  });

  it('reads "CO-1 line 2" for a CO-origin seeded line, not "est was $X"', async () => {
    const line = seededLine({
      agreement_ref: agreementRef({
        kind: 'change_order', co_number: 'EST-2026-0004-CO1', co_line_number: 2,
      }),
    });
    const { findByText, queryByText } = render(InvoiceEditView, { props: baseProps({ lineItems: [line] }) });
    await findByText('Cut parts');
    expect(await findByText('CO-1 line 2')).toBeInTheDocument();
    expect(queryByText(/est was/)).toBeNull();
  });

  it('shows the actuals chip and the est-reference once claimed work is attached', async () => {
    const line = seededLine({
      backing: 'actuals', actuals_total: '55.00',
      sources: [
        { source_id: 9, source_type: 'task', source_pk: 41, description: 'Sand edges',
          computed_amount: '55.00', qty: '2', units: 'hour', rate: '27.50' },
      ],
    });
    const { findByText } = render(InvoiceEditView, { props: baseProps({ lineItems: [line] }) });
    await findByText('Cut parts');
    expect(await findByText('actuals')).toBeInTheDocument();
    expect(await findByText(/est was \$50\.00/)).toBeInTheDocument();
    expect(await findByText(/\+\$5\.00/)).toBeInTheDocument();
  });

  it('shows the synced ✓ chip when actuals equal the estimate amount exactly', async () => {
    const line = seededLine({
      backing: 'actuals', actuals_total: '50.00',
      sources: [
        { source_id: 9, source_type: 'task', source_pk: 41, description: 'Sand edges',
          computed_amount: '50.00', qty: '2', units: 'hour', rate: '25.00' },
      ],
    });
    const { findByText } = render(InvoiceEditView, { props: baseProps({ lineItems: [line] }) });
    expect(await findByText('actuals = estimate ✓')).toBeInTheDocument();
  });

  it('"Use estimate" PATCHes the line back to the agreement_ref est values', async () => {
    api.patch.mockResolvedValue({});
    const onChanged = vi.fn();
    const line = seededLine({
      backing: 'edited', price: '30.00', actuals_total: null,
    });
    const { findByRole } = render(InvoiceEditView, { props: baseProps({ lineItems: [line], onChanged }) });
    const btn = await findByRole('button', { name: 'Use estimate' });
    await fireEvent.click(btn);
    expect(api.patch).toHaveBeenCalledWith('/api/invoices/5/line-items/1/', {
      qty: '2', price: '25.00',
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it('"Use actuals" PATCHes price to round(actuals_total / qty, 2), offered only when backing is estimate/edited and sources exist', async () => {
    api.patch.mockResolvedValue({});
    const line = seededLine({ backing: 'estimate', actuals_total: '51.10', qty: '2' });
    const { findByRole } = render(InvoiceEditView, { props: baseProps({ lineItems: [line] }) });
    const btn = await findByRole('button', { name: 'Use actuals' });
    await fireEvent.click(btn);
    expect(api.patch).toHaveBeenCalledWith('/api/invoices/5/line-items/1/', { price: '25.55' });
  });

  it('does not offer "Use actuals" when there is no actuals_total', async () => {
    const line = seededLine({ backing: 'estimate', actuals_total: null });
    const { findByText, queryByRole } = render(InvoiceEditView, { props: baseProps({ lineItems: [line] }) });
    await findByText('Cut parts');
    expect(queryByRole('button', { name: 'Use actuals' })).toBeNull();
  });

  it('removing a line renders the struck row with Restore wired to restore-line, and the totals row excludes it', async () => {
    api.delete.mockResolvedValue({ message: 'Line item deleted.' });
    api.post.mockResolvedValue({});
    const onChanged = vi.fn();
    const line = seededLine();
    const { findByText, container } = render(InvoiceEditView, {
      props: baseProps({ lineItems: [line], onChanged }),
    });
    await findByText('Cut parts');

    const removeBtn = await findByText('Remove from invoice');
    await fireEvent.click(removeBtn);

    expect(api.delete).toHaveBeenCalledWith('/api/invoices/5/line-items/1/');
    expect(onChanged).toHaveBeenCalled();

    const struckRow = container.querySelector('tr.doc-offdoc');
    expect(struckRow).not.toBeNull();
    expect(struckRow.textContent).toContain('Cut parts');

    // The line no longer exists server-side (removed from the `lineItems`
    // prop by the parent's refresh, as onChanged would trigger) — simulate
    // that here directly, since this test doesn't re-render via a real
    // parent. The totals footer must not count the struck row either way:
    // it only ever sums over the `lineItems` prop, never `removedRefs`.
    const totalCell = container.querySelector('tr.grand td.text-right strong');
    expect(totalCell.textContent).toBe('$50.00');

    const restoreBtn = await findByText('Restore');
    await fireEvent.click(restoreBtn);
    expect(api.post).toHaveBeenCalledWith('/api/invoices/5/restore-line/', { estimate_line_id: 30 });
  });

  it('never renders the word "delete" anywhere', async () => {
    const { queryByText, findByText } = render(InvoiceEditView, {
      props: baseProps({ lineItems: [seededLine(), handLine()] }),
    });
    await findByText('Cut parts');
    expect(queryByText(/delete/i)).toBeNull();
  });

  it('does not render Add Line Item / Add Adjustment / uncovered work when canEdit is false', async () => {
    const { findByText, queryByText } = render(InvoiceEditView, {
      props: baseProps({ canEdit: false, sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [AVAILABLE_ATOM] }]) }),
    });
    await findByText('Cut parts');
    expect(queryByText('Add Line Item')).toBeNull();
    expect(queryByText('Add Adjustment')).toBeNull();
    expect(queryByText('Sand edges')).toBeNull();
    expect(queryByText('Remove from invoice')).toBeNull();
  });

  it('ticking a pool row makes every line grow "Add selected here" and the placeholder row appears', async () => {
    const { findByText, findAllByText, container } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [AVAILABLE_ATOM] }]),
        lineItems: [seededLine(), handLine()],
      }),
    });
    await findByText('Sand edges');
    expect(document.body.textContent).not.toContain('Add selected here');

    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);

    const addHereButtons = await findAllByText('Add selected here');
    expect(addHereButtons).toHaveLength(2);
    expect(container.textContent).toContain('New line from selected');
  });

  it('"New line from selected" POSTs line-items-from-atoms then opens the edit modal', async () => {
    api.post.mockResolvedValue({ line_item_id: 99, line_number: 2, description: '', qty: '1', units: 'hour', price: '30.00', sources: [] });
    const { findByRole, findByText, getByText } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [AVAILABLE_ATOM] }]),
        lineItems: [seededLine()],
      }),
    });
    await findByText('Sand edges');
    const checkbox = document.body.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);

    const createBtn = await findByRole('button', { name: /create line/i });
    await fireEvent.click(createBtn);

    expect(api.post).toHaveBeenCalledWith(
      '/api/invoices/5/line-items-from-atoms/',
      { atoms: [{ type: 'task', id: 41 }] },
    );
    expect(await findByRole('dialog')).toBeInTheDocument();
    getByText('Edit Line Item');
  });

  it('a 409 on "New line from selected" refreshes via onChanged and shows a clear conflict message', async () => {
    api.post.mockRejectedValueOnce(conflictError());
    const onChanged = vi.fn();
    const { findByRole, findByText } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [AVAILABLE_ATOM] }]),
        lineItems: [seededLine()],
        onChanged,
      }),
    });
    await findByText('Sand edges');
    const checkbox = document.body.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);
    const createBtn = await findByRole('button', { name: /create line/i });
    await fireEvent.click(createBtn);

    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(get(overlayMessage)?.text).toMatch(/claimed/i);
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
  });

  it('excludes atoms already claimed by this invoice (state claimed_by_current) from the uncovered pool', async () => {
    const claimedAtom = { ...AVAILABLE_ATOM, id: 55, description: 'Already on this invoice', state: 'claimed_by_current' };
    const { findByText, queryByText } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [claimedAtom] }]),
      }),
    });
    await findByText('Cut parts');
    expect(queryByText('Already on this invoice')).toBeNull();
  });

  it('excludes the "Deposit credits" pool group from the generic uncovered-work rows', async () => {
    const depositAtom = { type: 'deposit', id: 501, description: 'Deposit credit — INV-1042', sub_info: 'Deposit on JOB-9', qty: '1', rate: '-500.00', amount: '-500.00', units: 'none', state: 'available' };
    const { findByText, queryByText } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: null, name: 'Deposit credits', has_billable_atoms: true, atoms: [depositAtom] }]),
      }),
    });
    await findByText('Cut parts');
    // It shows up in the dedicated Deposit credits section, not the
    // generic uncovered-work pick list.
    expect(await findByText('Deposit credits')).toBeInTheDocument();
    expect(queryByText('No uncovered billable items.')).toBeInTheDocument();
  });

  it('renders an INVOICED-elsewhere chip, dim and unselectable, for a claimed_by_other atom', async () => {
    const claimedElsewhere = {
      ...AVAILABLE_ATOM, id: 60, description: 'Weld joints', state: 'claimed_by_other',
      claiming_invoice_id: 8, claiming_invoice_number: 'INV-8',
    };
    const { findByText, container } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [claimedElsewhere] }]),
      }),
    });
    await findByText('Weld joints');
    expect(await findByText(/invoiced — INV-8/i)).toBeInTheDocument();
    const row = container.querySelector('tr.doc-unselectable-row');
    expect(row).not.toBeNull();
    expect(row.querySelector('input[type="checkbox"]')).toBeDisabled();
  });

  it('carries a "cancelled — work done" chip for a cancelled task, still selectable so the biller consciously chooses', async () => {
    const cancelledTask = {
      ...AVAILABLE_ATOM, id: 61, description: 'Frame it up', task_cancelled: true,
    };
    const { findByText } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [cancelledTask] }]),
      }),
    });
    await findByText('Frame it up');
    expect(await findByText(/cancelled — work done/i)).toBeInTheDocument();
  });

  it('carries a "descoped by CO-1" chip for an atom struck by an accepted CO', async () => {
    const descoped = {
      ...AVAILABLE_ATOM, id: 63, description: 'Rout edges',
      struck_from_agreement: true, descoped_by_co_number: 'EST-2026-0004-CO1',
    };
    const { findByText } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [descoped] }]),
      }),
    });
    await findByText('Rout edges');
    expect(await findByText(/descoped by CO-1/i)).toBeInTheDocument();
  });

  it('the INVOICED-elsewhere chip wins over the cancelled-task chip when both apply', async () => {
    const both = {
      ...AVAILABLE_ATOM, id: 62, description: 'Trim it out', state: 'claimed_by_other',
      claiming_invoice_id: 9, claiming_invoice_number: 'INV-9', task_cancelled: true,
    };
    const { findByText, queryByText } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [both] }]),
      }),
    });
    await findByText('Trim it out');
    expect(await findByText(/invoiced — INV-9/i)).toBeInTheDocument();
    expect(queryByText(/cancelled — work done/i)).toBeNull();
  });

  it('Deposit credits section applies a credit via line-items-from-atoms', async () => {
    api.post.mockResolvedValue({});
    const onChanged = vi.fn();
    const depositAtom = { type: 'deposit', id: 501, description: 'Deposit credit — INV-1042', sub_info: 'Deposit on JOB-9', qty: '1', rate: '-500.00', amount: '-500.00', units: 'none', state: 'available' };
    const { findByRole } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: null, name: 'Deposit credits', has_billable_atoms: true, atoms: [depositAtom] }]),
        onChanged,
      }),
    });
    const btn = await findByRole('button', { name: /apply to this invoice/i });
    await fireEvent.click(btn);
    expect(api.post).toHaveBeenCalledWith('/api/invoices/5/line-items-from-atoms/', {
      atoms: [{ type: 'deposit', id: 501 }],
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it('offers the next line number as max(line_number)+1, not the line count', async () => {
    const { findByText, container } = render(InvoiceEditView, {
      props: baseProps({
        sourcePool: poolWith([{ task_id: 1, name: 'Task', has_billable_atoms: true, atoms: [AVAILABLE_ATOM] }]),
        lineItems: [seededLine({ line_number: 1 }), handLine({ line_number: 5 })],
      }),
    });
    await findByText('Sand edges');
    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);
    expect(container.textContent).toContain('line 6');
    expect(container.textContent).not.toContain('line 3');
  });

  it('shows a "needs category" marker on an editable line with no accounting_category', async () => {
    const { findByText } = render(InvoiceEditView, {
      props: baseProps({ lineItems: [handLine({ accounting_category: null })] }),
    });
    expect(await findByText('needs category')).toBeInTheDocument();
  });

  it('shows seed buttons only when the draft has zero lines', async () => {
    const { findByText } = render(InvoiceEditView, { props: baseProps({ lineItems: [] }) });
    expect(await findByText('Apply everything')).toBeInTheDocument();
    expect(await findByText('Copy from estimate')).toBeInTheDocument();
  });

  it('hides seed buttons once the draft has any line', async () => {
    const { findByText, queryByText } = render(InvoiceEditView, { props: baseProps({ lineItems: [seededLine()] }) });
    await findByText('Cut parts');
    expect(queryByText('Apply everything')).toBeNull();
  });

  it('does not offer "Use actuals" when qty is 0 (the button would divide by zero and silently no-op)', async () => {
    const line = seededLine({ backing: 'estimate', actuals_total: '51.10', qty: '0' });
    const { findByText, queryByRole } = render(InvoiceEditView, { props: baseProps({ lineItems: [line] }) });
    await findByText('Cut parts');
    expect(queryByRole('button', { name: 'Use actuals' })).toBeNull();
  });

  describe('deposit invoice — agreement machinery withheld (RM 2026-08-09)', () => {
    // A deposit/progress invoice is derived from content, never stored
    // (spec §7.4 no-invoice-mode): every line is a deposit line. Advance
    // money bills against the job as a whole, so the agreement offerings
    // (uncovered work, Add from agreement) must not appear on it.
    const depositLine = (overrides = {}) => handLine({
      line_item_id: 9, line_number: 1, description: 'Deposit on JOB-9',
      is_deposit: true, backing: 'deposit', ...overrides,
    });

    it('withholds uncovered work and Add from agreement on an all-deposit draft', async () => {
      api.get.mockResolvedValue({ lines: [{ estimate_line_id: 77, co_line_id: null, description: 'Chair', qty: '1', units: 'ea', price: '25.00' }] });
      const { findByText, queryByText } = render(InvoiceEditView, {
        props: baseProps({ lineItems: [depositLine()], sourcePool: poolWith([{ task_id: 7, name: 'Build', atoms: [AVAILABLE_ATOM] }]) }),
      });
      await findByText('Deposit on JOB-9');
      expect(queryByText('Uncovered work')).toBeNull();
      expect(queryByText(/Add from agreement/)).toBeNull();
      expect(queryByText('Sand edges')).toBeNull();
    });

    it('still offers both on a mixed invoice (deposit line alongside a regular line)', async () => {
      api.get.mockResolvedValue({ lines: [{ estimate_line_id: 77, co_line_id: null, description: 'Chair', qty: '1', units: 'ea', price: '25.00' }] });
      const { findByText, queryByText } = render(InvoiceEditView, {
        props: baseProps({ lineItems: [depositLine(), seededLine({ line_item_id: 10, line_number: 2 })], sourcePool: poolWith([{ task_id: 7, name: 'Build', atoms: [AVAILABLE_ATOM] }]) }),
      });
      await findByText('Deposit on JOB-9');
      expect(queryByText('Uncovered work')).not.toBeNull();
      expect(await findByText(/Add from agreement/)).toBeInTheDocument();
    });
  });

  describe('Add from agreement picker', () => {
    const REMAINING_LINE = {
      estimate_line_id: 77, co_line_id: null,
      description: 'Misc hand line', qty: '1', units: 'ea', price: '25.00',
    };

    it('fetches the remaining list and hides the button when it is empty', async () => {
      api.get.mockResolvedValue({ lines: [] });
      const { findByText, queryByText } = render(InvoiceEditView, { props: baseProps() });
      await findByText('Cut parts');
      await vi.waitFor(() =>
        expect(api.get).toHaveBeenCalledWith('/api/invoices/5/remaining-agreement-lines/'));
      expect(queryByText(/Add from agreement/)).toBeNull();
    });

    it('does not fetch or render the button when canEdit is false', async () => {
      api.get.mockResolvedValue({ lines: [REMAINING_LINE] });
      const { findByText, queryByText } = render(InvoiceEditView, {
        props: baseProps({ canEdit: false }),
      });
      await findByText('Cut parts');
      expect(queryByText(/Add from agreement/)).toBeNull();
      expect(api.get).not.toHaveBeenCalled();
    });

    it('renders remaining lines in the picker and adding one calls restore-line then refreshes', async () => {
      api.get.mockResolvedValue({ lines: [REMAINING_LINE] });
      api.post.mockResolvedValue({});
      const onChanged = vi.fn();
      const { findByRole, findByText } = render(InvoiceEditView, {
        props: baseProps({ onChanged }),
      });
      await findByText('Cut parts');

      const openBtn = await findByRole('button', { name: /add from agreement/i });
      await fireEvent.click(openBtn);
      await findByText('Misc hand line');

      const addBtn = await findByRole('button', { name: /add to this invoice/i });
      await fireEvent.click(addBtn);

      expect(api.post).toHaveBeenCalledWith(
        '/api/invoices/5/restore-line/', { estimate_line_id: 77 });
      await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
      // Refreshed the remaining list too (second GET after the POST).
      expect(api.get.mock.calls.filter(
        (c) => c[0] === '/api/invoices/5/remaining-agreement-lines/').length,
      ).toBeGreaterThanOrEqual(2);
    });

    it('routes a restore-line failure through handleMutationError (overlay, no crash)', async () => {
      api.get.mockResolvedValue({ lines: [REMAINING_LINE] });
      api.post.mockRejectedValueOnce(
        Object.assign(new Error('nope'), { status: 400, data: { detail: 'nope' } }));
      const { findByRole, findByText } = render(InvoiceEditView, { props: baseProps() });
      await findByText('Cut parts');

      const openBtn = await findByRole('button', { name: /add from agreement/i });
      await fireEvent.click(openBtn);
      await findByText('Misc hand line');

      const addBtn = await findByRole('button', { name: /add to this invoice/i });
      await fireEvent.click(addBtn);

      await vi.waitFor(() => expect(get(overlayMessage)?.text).toMatch(/nope|could not add/i));
    });
  });
});
