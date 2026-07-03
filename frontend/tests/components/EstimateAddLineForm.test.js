import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
import { api } from '@/lib/api.js';
import EstimateAddLineForm from '@/components/estimates/EstimateAddLineForm.svelte';

const cats = [{ id: 7, code: 'MAT', name: 'Materials' }];
beforeEach(() => { api.post.mockReset(); api.post.mockResolvedValue({ line_item_id: 1 }); });

describe('EstimateAddLineForm', () => {
  it('service choice posts service_item + qty', async () => {
    const onSaved = vi.fn();
    const choice = { type: 'service', serviceItem: { template_id: 11, template_name: 'CNC Routing' } };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '3' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items-from-service/',
      { service_item: 11, qty: '3' });
    expect(onSaved).toHaveBeenCalled();
  });

  it('inventory choice posts inventory_item + qty', async () => {
    const choice = { type: 'inventory', inventoryItem: { inventory_item_id: 22, code: 'BOLT-14' } };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '10' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      { inventory_item: 22, qty: '10' });
  });

  it('freeform fee posts manual payload with is_material false; description prefilled from typed', async () => {
    const choice = { type: 'freeform', typed: 'Rush charge', isMaterial: false };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByLabelText(/description/i)).toHaveValue('Rush charge');
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '50' } });
    await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      expect.objectContaining({ description: 'Rush charge', is_material: false, accounting_category: 7, price: '50' }));
  });

  it('freeform material prefills AC from the default and carries is_material true (no manual AC)', async () => {
    const choice = { type: 'freeform', typed: 'plywood', isMaterial: true };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats,
        defaultMaterialCategoryId: 7, onSaved: vi.fn() },
    });
    // AC is prefilled from the default — the user enters no AC.
    expect(getByLabelText(/accounting category/i)).toHaveValue('7');
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '30' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      expect.objectContaining({ is_material: true, accounting_category: 7 }));
  });

  it('freeform material does not block save when no default is configured (backend fills it)', async () => {
    const choice = { type: 'freeform', typed: 'plywood', isMaterial: true };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats,
        defaultMaterialCategoryId: null, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '30' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    // Not blocked on AC — material defers to the backend default.
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      expect.objectContaining({ is_material: true }));
  });

  it('shows the base unit next to quantity for a service pick', () => {
    const choice = { type: 'service', serviceItem: {
      template_id: 11, template_name: 'CNC Routing', rate_scheme_detail: { unit_label: 'hr' } } };
    const { getByText } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByText('hr')).toBeInTheDocument();
  });

  it('shows the base unit next to quantity for an inventory pick', () => {
    const choice = { type: 'inventory', inventoryItem: {
      inventory_item_id: 22, code: 'BOLT-14', units: 'ea' } };
    const { getByText } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByText('ea')).toBeInTheDocument();
  });

  it('freeform fee blocks save with no accounting category (hand-line rule)', async () => {
    const choice = { type: 'freeform', typed: 'x', isMaterial: false };
    const { getByLabelText, getByRole, findByText } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).not.toHaveBeenCalled();
    expect(await findByText(/accounting category is required/i)).toBeInTheDocument();
  });
});
