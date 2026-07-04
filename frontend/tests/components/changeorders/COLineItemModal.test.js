import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

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

describe('COLineItemModal', () => {
  it('creates an "add" line with an accounting category', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(COLineItemModal, {
      props: { open: true, mode: 'create', coId: 3, categories: cats, onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'New line' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/Price/), { target: { value: '50' } });
    await fireEvent.change(getByLabelText(/Accounting Category/), { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/change-orders/3/line-items/', {
      action: 'add', target_line_item: null, description: 'New line', qty: 2, units: 'none', price: 50,
      accounting_category: 7,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('blocks an "add" line with no accounting category (send-guard rule)', async () => {
    const { getByLabelText, getByRole, findByText } = render(COLineItemModal, {
      props: { open: true, mode: 'create', coId: 3, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'New line' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).not.toHaveBeenCalled();
    expect(await findByText(/accounting category is required/i)).toBeInTheDocument();
  });

  it('does not require or send an accounting category on a replace line (inherits from the replaced atom)', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole, queryByLabelText } = render(COLineItemModal, {
      props: {
        open: true, mode: 'create', coId: 3, categories: cats, onSaved,
        estimateLines: [{ line_item_id: 7, line_number: 1, description: 'Old', price: 10, qty: 1, units: 'ea' }],
        initialAction: 'replace', initialTarget: 7,
      },
    });
    expect(queryByLabelText(/Accounting Category/)).toBeNull();
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Revised' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/change-orders/3/line-items/',
      expect.not.objectContaining({ accounting_category: expect.anything() }));
    expect(onSaved).toHaveBeenCalled();
  });

  it('prefills the accounting category when editing an add line', async () => {
    const item = {
      line_item_id: 9, action: 'add', target_line_item: null,
      description: 'Existing', qty: '1.00', units: 'ea', price: '25.00',
      accounting_category: 7,
    };
    const { getByLabelText } = render(COLineItemModal, {
      props: { open: true, mode: 'edit', coId: 3, item, categories: cats },
    });
    expect(getByLabelText(/Accounting Category/)).toHaveValue('7');
  });

  it('hides the line fields for a plain remove', async () => {
    const { getByLabelText, queryByLabelText } = render(COLineItemModal, {
      props: {
        open: true, mode: 'create', coId: 3,
        estimateLines: [{ line_item_id: 7, line_number: 1, description: 'Old', price: 10, qty: 1, units: 'ea' }],
      },
    });
    await fireEvent.change(getByLabelText(/Action/), { target: { value: 'remove' } });
    expect(queryByLabelText(/Description/)).toBeNull();
    expect(getByLabelText(/Target estimate line/)).toBeInTheDocument();
  });
});
