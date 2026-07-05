import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => (e && e.message) || fallback || 'Request failed.',
}));

import { api } from '@/lib/api.js';
import MaterialModal from '@/components/MaterialModal.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect / InventoryItemPicker
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('MaterialModal', () => {
  it('creates a freeform material on a task (cost is document-sourced, not typed)', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(MaterialModal, {
      props: { open: true, mode: 'create', taskId: 10, onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Steel' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '2' } });
    // Unit Cost is disabled for a freeform material — not set here.
    await fireEvent.input(getByLabelText(/Sell Price/), { target: { value: '8' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/tasks/10/materials/', {
      description: 'Steel', quantity: 2, units: 'none', unit_cost: '0', sell_price: 8,
      inventory_item: null, accounting_category: null,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('disables the unit cost field for a freeform (no-PLI) material', () => {
    const { getByLabelText } = render(MaterialModal, {
      props: { open: true, mode: 'create', taskId: 10 },
    });
    expect(getByLabelText(/Unit Cost/)).toBeDisabled();
  });

  it('prompts to propagate a PLI price change, then patches with the flag', async () => {
    const { getByLabelText, getByRole, getByText } = render(MaterialModal, {
      props: {
        open: true, mode: 'edit',
        material: { material_id: 1, inventory_item: 99, unit_cost: 5, sell_price: 10, units: 'none', quantity: 2, description: 'X' },
      },
    });
    await fireEvent.input(getByLabelText(/Unit Cost/), { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    // pricing differs from the PLI → propagate prompt appears (no API yet)
    expect(getByText('Update PLI with the new values?')).toBeInTheDocument();
    expect(api.patch).not.toHaveBeenCalled();

    await fireEvent.click(getByRole('button', { name: 'Yes, update PLI' }));
    expect(api.patch).toHaveBeenCalledWith('/api/materials/1/', {
      unit_cost: 7, sell_price: 10, propagate_to_pli: true,
    });
  });

  function mockEarmarkedItem() {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/inventory/')) {
        return Promise.resolve({ results: [{
          inventory_item_id: 1, code: 'FELT', description: 'grey felt',
          units: 'sheet', purchase_price: '4', selling_price: '8',
          qty_on_hand: '5.00', qty_earmarked: '2.00', qty_available: '3.00',
        }] });
      }
      return Promise.resolve([]); // UnitsSelect
    });
  }

  it('warns that a picked item is earmarked for other jobs (allocation visibility)', async () => {
    mockEarmarkedItem();
    const { getByPlaceholderText, findByText } = render(MaterialModal, {
      props: { open: true, mode: 'create', taskId: 10 },
    });
    await fireEvent.input(getByPlaceholderText('Search inventory items…'), { target: { value: 'felt' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByText(/grey felt/));
    expect(await findByText(/earmarked for other jobs/)).toBeInTheDocument();
  });

  it('warns when the requested quantity exceeds what is available', async () => {
    mockEarmarkedItem();
    const { getByPlaceholderText, findByText, getByLabelText } = render(MaterialModal, {
      props: { open: true, mode: 'create', taskId: 10 },
    });
    await fireEvent.input(getByPlaceholderText('Search inventory items…'), { target: { value: 'felt' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByText(/grey felt/));
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '4' } });
    expect(await findByText(/Only 3.00 of 5.00/)).toBeInTheDocument();
  });

  it('renders API field errors under the matching inputs', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Bad request',
      data: { quantity: ['A valid number is required.'], sell_price: ['A valid number is required too.'] },
    });
    const { getByLabelText, getByRole, findByText } = render(MaterialModal, {
      props: { open: true, mode: 'create', taskId: 10 },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Steel' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByText('A valid number is required.')).toHaveClass('field-error');
    expect(await findByText('A valid number is required too.')).toHaveClass('field-error');
  });

  it('renders an operation error in the form footer after the buttons', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Job is not editable.',
      data: { detail: 'Job is not editable.' },
    });
    const { getByLabelText, getByRole, findByRole } = render(MaterialModal, {
      props: { open: true, mode: 'create', taskId: 10 },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Steel' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByRole('alert')).toHaveTextContent('Job is not editable.');
  });

  it('clears a stale field error when the user edits a field', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Bad request',
      data: { quantity: ['A valid number is required.'] },
    });
    const { getByLabelText, getByRole, findByText, queryByText } = render(MaterialModal, {
      props: { open: true, mode: 'create', taskId: 10 },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Steel' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText('A valid number is required.')).toBeInTheDocument();

    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '3' } });
    expect(queryByText('A valid number is required.')).toBeNull();
  });

  it('seeds description from presetDescription on create', async () => {
    const { getByLabelText } = render(MaterialModal, {
      props: { open: true, mode: 'create', jobId: 5, categories: [], presetDescription: 'plywood' },
    });
    expect(getByLabelText(/description/i)).toHaveValue('plywood');
  });

  it('prefills from presetPli on create (PLI-locked)', async () => {
    const pli = { inventory_item_id: 22, code: 'BOLT-14', description: 'Hex bolt',
      purchase_price: '0.25', selling_price: '0.50', units: 'ea' };
    const { getByLabelText } = render(MaterialModal, {
      props: { open: true, mode: 'create', jobId: 5, categories: [], presetPli: pli },
    });
    expect(getByLabelText(/description/i)).toHaveValue('Hex bolt');
  });

  it('freeform create (no presetPli) prefills AC from defaultMaterialCategoryId', async () => {
    const cats = [{ id: 7, code: 'MAT', name: 'Materials' }];
    const { getByLabelText } = render(MaterialModal, {
      props: { open: true, mode: 'create', jobId: 5, categories: cats, defaultMaterialCategoryId: 7 },
    });
    expect(getByLabelText(/accounting category/i)).toHaveValue('7');
  });
});
