import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => (e && e.message) || fallback || 'Request failed.',
}));

import { api } from '@/lib/api.js';
import COLineItemModal from '@/components/changeorders/COLineItemModal.svelte';

const cats = [{ id: 7, code: 'SVC', name: 'Service' }];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('COLineItemModal — edit-fields variant (PATCH, gestures preset lineItemId)', () => {
  it('PATCHes description/qty/units/price with no action/target keys', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(COLineItemModal, {
      props: {
        open: true, variant: 'edit-fields', coId: 3, lineItemId: 12,
        initialDescription: 'Widget C v2', initialUnits: 'ea',
        categories: cats, onSaved,
      },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Widget C v3' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '5' } });
    await fireEvent.input(getByLabelText(/Price/), { target: { value: '30' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.patch).toHaveBeenCalledWith('/api/change-orders/3/line-items/12/', {
      description: 'Widget C v3', qty: 5, units: 'ea', price: 30,
    });
    expect(api.post).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalled();
  });

  it('requires and sends an accounting category when needsAccountingCategory (editing an add line)', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole, findByText } = render(COLineItemModal, {
      props: {
        open: true, variant: 'edit-fields', coId: 3, lineItemId: 13,
        needsAccountingCategory: true,
        initialDescription: 'Extra Item', initialUnits: 'ea',
        categories: cats, onSaved,
      },
    });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/Price/), { target: { value: '60' } });

    // Blocked without an AC.
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).not.toHaveBeenCalled();
    expect(await findByText(/accounting category is required/i)).toBeInTheDocument();

    await fireEvent.change(getByLabelText(/Accounting Category/), { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.patch).toHaveBeenCalledWith('/api/change-orders/3/line-items/13/', {
      description: 'Extra Item', qty: 2, units: 'ea', price: 60, accounting_category: 7,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('prefills fields from the initial* props', () => {
    const { getByLabelText } = render(COLineItemModal, {
      props: {
        open: true, variant: 'edit-fields', coId: 3, lineItemId: 13, needsAccountingCategory: true,
        initialDescription: 'Extra Item', initialQty: '2', initialUnits: 'ea', initialPrice: '60',
        initialAccountingCategory: 7, categories: cats,
      },
    });
    expect(getByLabelText(/Description/)).toHaveValue('Extra Item');
    expect(getByLabelText(/Quantity/)).toHaveValue(2);
    expect(getByLabelText(/Price/)).toHaveValue(60);
    expect(getByLabelText(/Accounting Category/)).toHaveValue('7');
  });
});

describe('COLineItemModal — replace-prefill variant (POST, gestures preset targetLineItem)', () => {
  it('POSTs action=replace with the target and edited fields, no AC field at all', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole, queryByLabelText } = render(COLineItemModal, {
      props: {
        open: true, variant: 'replace-prefill', coId: 3, targetLineItem: 7,
        initialDescription: 'Widget A', initialUnits: 'ea',
        onSaved,
      },
    });
    expect(queryByLabelText(/Accounting Category/)).toBeNull();
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/Price/), { target: { value: '120' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/change-orders/3/line-items/', {
      description: 'Widget A', qty: 2, units: 'ea', price: 120,
      action: 'replace', target_line_item: 7,
    });
    expect(onSaved).toHaveBeenCalled();
  });
});

describe('COLineItemModal — adjustment variant (percent only, readback before close)', () => {
  it('create: POSTs action=replace with adjustment_percent, then shows the computed readback and waits for an explicit Done', async () => {
    api.post.mockResolvedValue({ price: '7.00', adjustment_percent: '5.00' });
    const onSaved = vi.fn();
    const { getByLabelText, getByRole, findByText, queryByLabelText } = render(COLineItemModal, {
      props: {
        open: true, variant: 'adjustment', coId: 3, targetLineItem: 9,
        initialDescription: 'Rush 10%', initialPercent: '10',
        onSaved,
      },
    });
    expect(queryByLabelText(/Quantity/)).toBeNull();
    await fireEvent.input(getByLabelText(/Percent/), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/change-orders/3/line-items/', {
      description: 'Rush 10%', adjustment_percent: 5, action: 'replace', target_line_item: 9,
    });
    // Readback shown, modal not yet closed via onSaved — the user must
    // explicitly dismiss it (saves stay explicit, no auto-close). Matched
    // via a text function since the amount sits in a nested <strong>.
    expect(await findByText((_, node) => node.textContent === 'This line now computes to $7.00.')).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();

    await fireEvent.click(getByRole('button', { name: 'Done' }));
    expect(onSaved).toHaveBeenCalled();
  });

  it('edit: PATCHes adjustment_percent/description only, no action/target keys', async () => {
    api.patch.mockResolvedValue({ price: '5.00' });
    const { getByLabelText, getByRole, findByText } = render(COLineItemModal, {
      props: {
        open: true, variant: 'adjustment', coId: 3, lineItemId: 12,
        initialDescription: 'Rush 10% (revised)', initialPercent: '10',
      },
    });
    await fireEvent.input(getByLabelText(/Percent/), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.patch).toHaveBeenCalledWith('/api/change-orders/3/line-items/12/', {
      description: 'Rush 10% (revised)', adjustment_percent: 5,
    });
    expect(api.post).not.toHaveBeenCalled();
    expect(await findByText((_, node) => node.textContent === 'This line now computes to $5.00.')).toBeInTheDocument();
  });
});

describe('COLineItemModal error display', () => {
  it('renders API field errors under the matching inputs', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Bad request',
      data: { qty: ['A valid number is required.'] },
    });
    const { getByRole, findByText } = render(COLineItemModal, {
      props: { open: true, variant: 'replace-prefill', coId: 3, targetLineItem: 7, initialDescription: 'X' },
    });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByText('A valid number is required.')).toHaveClass('field-error');
  });

  it('renders an operation error in the form footer after the buttons', async () => {
    api.patch.mockRejectedValue({
      status: 400,
      message: 'Change order is not editable.',
      data: { detail: 'Change order is not editable.' },
    });
    const { getByRole, findByRole } = render(COLineItemModal, {
      props: { open: true, variant: 'edit-fields', coId: 3, lineItemId: 12, initialDescription: 'X' },
    });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByRole('alert')).toHaveTextContent('Change order is not editable.');
  });
});

describe('COLineItemModal Cancel', () => {
  it('calls onClose and never calls the API', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(COLineItemModal, {
      props: { open: true, variant: 'edit-fields', coId: 3, lineItemId: 12, initialDescription: 'X', onClose },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
    expect(api.patch).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });
});
