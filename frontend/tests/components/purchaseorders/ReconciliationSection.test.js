import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import ReconciliationSection from '@/components/purchaseorders/ReconciliationSection.svelte';

function po(overrides = {}) {
  return {
    po_id: 1, status: 'issued',
    bill_total: null, vendor_invoice_ref: '', reconciled: false, reconciled_date: null,
    variance: null,
    line_items: [
      { line_item_id: 1, line_number: 1, description: 'Outsourced work', qty: 1,
        price: '100.00', final_price: null, invoice_only: false },
      { line_item_id: 2, line_number: 2, description: 'Widget', qty: 2,
        price: '10.00', final_price: null, invoice_only: false },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect etc.
});

describe('ReconciliationSection — hidden states', () => {
  it('renders nothing for a draft PO', () => {
    const { container } = render(ReconciliationSection, {
      props: { po: po({ status: 'draft' }), canManageFinancials: true },
    });
    expect(container.textContent).not.toContain('Reconciliation');
  });

  it('renders nothing for a non-financials user on an unreconciled PO', () => {
    const { container } = render(ReconciliationSection, {
      props: { po: po(), canManageFinancials: false },
    });
    expect(container.querySelector('dl')).toBeNull();
  });
});

describe('ReconciliationSection — identity save', () => {
  it('resends the current state unchanged when nothing is edited', async () => {
    const onReconcile = vi.fn();
    const p = po({
      bill_total: '120.00', vendor_invoice_ref: 'VEND-1', reconciled: true,
      variance: '0.00',
      line_items: [
        { line_item_id: 1, line_number: 1, description: 'Outsourced work', qty: 1,
          price: '100.00', final_price: '110.00', invoice_only: false },
        { line_item_id: 2, line_number: 2, description: 'Freight', qty: 1,
          price: '10.00', final_price: null, invoice_only: true, units: 'ea',
          accounting_category: '', task: null },
      ],
    });
    const { getByRole } = render(ReconciliationSection, {
      props: { po: p, canManageFinancials: true, onReconcile },
    });
    await fireEvent.click(getByRole('button', { name: 'Update reconciliation' }));

    expect(onReconcile).toHaveBeenCalledWith({
      bill_total: '120.00',
      vendor_invoice_ref: 'VEND-1',
      line_finals: { 1: '110.00' },
      appended_lines: [
        { line_item_id: 2, description: 'Freight', qty: 1, units: 'ea', price: '10.00' },
      ],
    });
  });

  it('omits a line with no final price from line_finals (as-ordered stays as-ordered)', async () => {
    const onReconcile = vi.fn();
    const { getByRole } = render(ReconciliationSection, {
      props: { po: po(), canManageFinancials: true, onReconcile },
    });
    await fireEvent.click(getByRole('button', { name: 'Reconcile' }));
    expect(onReconcile.mock.calls[0][0].line_finals).toEqual({});
  });
});

describe('ReconciliationSection — edits', () => {
  it('includes an edited final price in the payload', async () => {
    const onReconcile = vi.fn();
    const { getByRole, container } = render(ReconciliationSection, {
      props: { po: po(), canManageFinancials: true, onReconcile },
    });
    const inputs = container.querySelectorAll('table.data-table input[type="number"]');
    await fireEvent.input(inputs[0], { target: { value: '95.00' } });
    await fireEvent.click(getByRole('button', { name: 'Reconcile' }));
    // type="number" inputs bind as numbers (same convention as LineItemForm).
    expect(onReconcile.mock.calls[0][0].line_finals).toEqual({ 1: 95 });
  });

  it('adds and removes a same-session (unsaved) invoice-only line before save with no confirm', async () => {
    vi.stubGlobal('confirm', vi.fn());
    const onReconcile = vi.fn();
    const { getByRole, queryByText } = render(ReconciliationSection, {
      props: { po: po(), canManageFinancials: true, onReconcile },
    });
    await fireEvent.click(getByRole('button', { name: 'Add Invoice-Only Line' }));
    await fireEvent.click(getByRole('button', { name: 'Remove' }));
    expect(window.confirm).not.toHaveBeenCalled();
    // A same-session draft row was never persisted — nothing at risk, no notice.
    expect(queryByText(/will be deleted when you save/)).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Reconcile' }));
    expect(onReconcile.mock.calls[0][0].appended_lines).toEqual([]);
  });
});

describe('ReconciliationSection — removing a persisted invoice-only line', () => {
  function poWithPersistedAppended() {
    return po({
      reconciled: true,
      line_items: [
        { line_item_id: 1, line_number: 1, description: 'Outsourced work', qty: 1,
          price: '100.00', final_price: null, invoice_only: false },
        { line_item_id: 2, line_number: 2, description: 'Widget', qty: 2,
          price: '10.00', final_price: null, invoice_only: false },
        { line_item_id: 3, line_number: 3, description: 'Freight', qty: 1,
          price: '15.00', final_price: null, invoice_only: true, units: 'ea',
          accounting_category: '', task: null },
      ],
    });
  }

  it('shows a delete notice (no confirm) and omits the row from the save payload', async () => {
    vi.stubGlobal('confirm', vi.fn());
    const onReconcile = vi.fn();
    const { getByRole, getAllByRole, getByText, queryByText } = render(ReconciliationSection, {
      props: { po: poWithPersistedAppended(), canManageFinancials: true, onReconcile },
    });

    expect(queryByText(/will be deleted when you save/)).toBeNull();

    const removeButtons = getAllByRole('button', { name: 'Remove' });
    await fireEvent.click(removeButtons[0]); // the only appended row: Freight
    expect(window.confirm).not.toHaveBeenCalled();

    expect(getByText(/1\s*recorded line will be deleted when you save/)).toBeInTheDocument();
    expect(getByText('Freight')).toBeInTheDocument(); // named in the notice list

    await fireEvent.click(getByRole('button', { name: 'Update reconciliation' }));
    expect(onReconcile.mock.calls[0][0].appended_lines).toEqual([]);
  });

  it('clears the notice and restores the row to the payload on Re-add', async () => {
    const onReconcile = vi.fn();
    const { getByRole, getAllByRole, queryByText } = render(ReconciliationSection, {
      props: { po: poWithPersistedAppended(), canManageFinancials: true, onReconcile },
    });

    await fireEvent.click(getAllByRole('button', { name: 'Remove' })[0]);
    expect(queryByText(/will be deleted when you save/)).toBeInTheDocument();

    await fireEvent.click(getByRole('button', { name: 'Re-add' }));
    expect(queryByText(/will be deleted when you save/)).toBeNull();

    await fireEvent.click(getByRole('button', { name: 'Update reconciliation' }));
    expect(onReconcile.mock.calls[0][0].appended_lines).toEqual([
      { line_item_id: 3, description: 'Freight', qty: 1, units: 'ea', price: '15.00' },
    ]);
  });
});

describe('ReconciliationSection — variance display', () => {
  it('formats a non-null variance as money', () => {
    const { getByText } = render(ReconciliationSection, {
      props: { po: po({ variance: '-15.50' }), canManageFinancials: true },
    });
    expect(getByText(/-\$15.50/)).toBeInTheDocument();
  });
});

describe('ReconciliationSection — read-only summary', () => {
  it('shows a read-only summary to non-financials users once reconciled', () => {
    const { getByText, queryByRole } = render(ReconciliationSection, {
      props: {
        po: po({ bill_total: '120.00', vendor_invoice_ref: 'VEND-1', reconciled: true, variance: '20.00' }),
        canManageFinancials: false,
      },
    });
    expect(getByText('VEND-1')).toBeInTheDocument();
    expect(queryByRole('button', { name: /Reconcile/ })).toBeNull();
  });
});
