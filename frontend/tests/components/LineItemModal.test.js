import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => (e && e.message) || fallback || 'Request failed.',
}));

import { api } from '@/lib/api.js';
import LineItemModal from '@/components/LineItemModal.svelte';

const SAMPLE_CATEGORIES = [
  { id: 42, code: 'LAB', name: 'Labor' },
  { id: 99, code: 'MAT', name: 'Materials' },
];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect (/api/settings/units/) + InventoryItemPicker
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('LineItemModal', () => {
  it('creates a manual line item against the given apiBase', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/7',
        onSaved, categories: SAMPLE_CATEGORIES,
      },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Widget' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '5' } });
    await fireEvent.input(getByLabelText('Price'), { target: { value: '10' } });
    // Select a category so the AC validation passes
    await fireEvent.change(getByLabelText(/Accounting Category/), { target: { value: '42' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/line-items/', {
      description: 'Widget', qty: 5, units: 'none', price: 10, accounting_category: 42,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('patches an existing line item in edit mode', async () => {
    const onSaved = vi.fn();
    const item = {
      line_item_id: 3, description: 'Old', qty: 2, units: 'none', price: 4,
      accounting_category: 42,
    };
    const { getByLabelText, getByRole } = render(LineItemModal, {
      props: {
        open: true, mode: 'edit', apiBase: '/api/estimates/7', item,
        onSaved, categories: SAMPLE_CATEGORIES,
      },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'New' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.patch).toHaveBeenCalledWith('/api/estimates/7/line-items/3/', {
      description: 'New', qty: 2, units: 'none', price: 4, accounting_category: 42,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('requires an accounting category in manual create mode', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole, findByText } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/7',
        onSaved, categories: SAMPLE_CATEGORIES,
      },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Widget' } });
    await fireEvent.input(getByLabelText('Price'), { target: { value: '10' } });
    // Do NOT select a category — leave it blank
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByText('Accounting Category is required.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('requires an accounting category in manual edit mode', async () => {
    const onSaved = vi.fn();
    // Item has a null accounting_category (bad historical data)
    const item = {
      line_item_id: 5, description: 'Old', qty: 1, units: 'none', price: 5,
      accounting_category: null,
    };
    const { getByRole, findByText } = render(LineItemModal, {
      props: {
        open: true, mode: 'edit', apiBase: '/api/invoices/3', item,
        onSaved, categories: SAMPLE_CATEGORIES,
      },
    });
    // Save without selecting a category
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByText('Accounting Category is required.')).toBeInTheDocument();
    expect(api.patch).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('requires an inventory item before saving in catalog mode', async () => {
    const { getByLabelText, getByRole, findByText } = render(LineItemModal, {
      props: { open: true, mode: 'create', apiBase: '/api/estimates/7' },
    });
    await fireEvent.click(getByLabelText(/From Inventory/));
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByText('Select an inventory item.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('renders API field errors under the matching inputs', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Bad request',
      data: { qty: ['A valid number is required.'], price: ['Ensure this value is greater than or equal to 0.'] },
    });
    const { getByLabelText, getByRole, findByText } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/7',
        categories: SAMPLE_CATEGORIES,
      },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Widget' } });
    await fireEvent.change(getByLabelText(/Accounting Category/), { target: { value: '42' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByText('A valid number is required.')).toHaveClass('field-error');
    expect(await findByText('Ensure this value is greater than or equal to 0.')).toHaveClass('field-error');
  });

  it('renders an operation error in the form footer after the buttons', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Estimate is not editable.',
      data: { detail: 'Estimate is not editable.' },
    });
    const { getByLabelText, getByRole, findByRole } = render(LineItemModal, {
      props: {
        open: true, mode: 'create', apiBase: '/api/estimates/7',
        categories: SAMPLE_CATEGORIES,
      },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Widget' } });
    await fireEvent.change(getByLabelText(/Accounting Category/), { target: { value: '42' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByRole('alert')).toHaveTextContent('Estimate is not editable.');
  });

  it('closes via onClose', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(LineItemModal, {
      props: { open: true, mode: 'create', apiBase: '/api/estimates/7', onClose },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe('LineItemModal — freeform_kind (read-only; kind is immutable so no editor)', () => {
  it('displays the kind read-only in edit mode and never renders an editable marker', () => {
    const item = {
      line_item_id: 3, description: 'Plywood', qty: 2, units: 'sheet', price: '40.00',
      accounting_category: 42, freeform_kind: 'material',
    };
    const { getByText, queryByLabelText } = render(LineItemModal, {
      props: {
        open: true, mode: 'edit', apiBase: '/api/estimates/7', item,
        categories: SAMPLE_CATEGORIES, showMaterialMarker: true,
      },
    });
    expect(getByText(/kind/i)).toBeInTheDocument();
    expect(getByText('Material')).toBeInTheDocument();
    expect(queryByLabelText(/is this a material/i)).toBeNull();
  });

  it('does not require a manually chosen AC on an existing material line (defers to the backend default)', async () => {
    const onSaved = vi.fn();
    const item = {
      line_item_id: 3, description: 'Plywood', qty: 2, units: 'sheet', price: '40.00',
      accounting_category: null, freeform_kind: 'material',
    };
    const { getByRole } = render(LineItemModal, {
      props: {
        open: true, mode: 'edit', apiBase: '/api/estimates/7', item, onSaved,
        categories: SAMPLE_CATEGORIES, showMaterialMarker: true,
      },
    });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledTimes(1);
    const [, payload] = api.patch.mock.calls[0];
    expect(payload).not.toHaveProperty('is_material');
    expect(onSaved).toHaveBeenCalled();
  });

  it('renders no kind row and no checkbox when the line has no freeform_kind (catalog/service line)', () => {
    const item = {
      line_item_id: 4, description: 'Bolt', qty: 5, units: 'ea', price: '1.00',
      accounting_category: 42, freeform_kind: null,
    };
    const { queryByText, queryByLabelText } = render(LineItemModal, {
      props: {
        open: true, mode: 'edit', apiBase: '/api/estimates/7', item,
        categories: SAMPLE_CATEGORIES, showMaterialMarker: true,
      },
    });
    expect(queryByText(/^kind/i)).toBeNull();
    expect(queryByLabelText(/is this a material/i)).toBeNull();
  });

  it('never sends is_material when showMaterialMarker is false (invoice surface)', async () => {
    const onSaved = vi.fn();
    const item = {
      line_item_id: 5, description: 'Widget', qty: 1, units: 'none', price: '10.00',
      accounting_category: 42,
    };
    const { getByRole } = render(LineItemModal, {
      props: {
        open: true, mode: 'edit', apiBase: '/api/invoices/3', item, onSaved,
        categories: SAMPLE_CATEGORIES,
      },
    });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const [, payload] = api.patch.mock.calls[0];
    expect(payload).not.toHaveProperty('is_material');
    expect(onSaved).toHaveBeenCalled();
  });
});
