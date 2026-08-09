import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
import { api } from '@/lib/api.js';
import COAddLineForm from '@/components/changeorders/COAddLineForm.svelte';

const cats = [{ id: 7, code: 'MAT', name: 'Materials' }];
beforeEach(() => { api.post.mockReset(); api.post.mockResolvedValue({ line_item_id: 1 }); });

describe('COAddLineForm', () => {
  it('service choice posts service_item + qty to the CO from-service endpoint', async () => {
    const onSaved = vi.fn();
    const choice = { type: 'service', serviceItem: { template_id: 11, template_name: 'CNC Routing' } };
    const { getByLabelText, getByRole } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats, onSaved },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '3' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items-from-service/',
      { service_item: 11, qty: '3' });
    expect(onSaved).toHaveBeenCalled();
  });

  it('inventory choice posts action add + inventory_item + qty', async () => {
    const choice = { type: 'inventory', inventoryItem: { inventory_item_id: 22, code: 'BOLT-14' } };
    const { getByLabelText, getByRole } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '10' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/',
      { action: 'add', inventory_item: 22, qty: '10' });
  });

  it('freeform plain line posts a manual add payload; description prefilled from typed', async () => {
    const choice = { type: 'freeform', typed: 'Rush charge', isMaterial: false };
    const { getByLabelText, getByRole } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByLabelText(/description/i)).toHaveValue('Rush charge');
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '50' } });
    await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/',
      expect.objectContaining({
        action: 'add', description: 'Rush charge', is_material: false,
        accounting_category: 7, price: '50',
      }));
  });

  it('freeform material prefills AC from the default and carries is_material true', async () => {
    const choice = { type: 'freeform', typed: 'plywood', isMaterial: true };
    const { getByLabelText, getByRole } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats,
        defaultMaterialCategoryId: 7, onSaved: vi.fn() },
    });
    expect(getByLabelText(/accounting category/i)).toHaveValue('7');
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '30' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/',
      expect.objectContaining({ action: 'add', is_material: true, accounting_category: 7 }));
  });

  it('freeform material does not block save when no default is configured (backend fills it)', async () => {
    const choice = { type: 'freeform', typed: 'plywood', isMaterial: true };
    const { getByLabelText, getByRole } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats,
        defaultMaterialCategoryId: null, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '30' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/',
      expect.objectContaining({ action: 'add', is_material: true }));
  });

  it('freeform plain line blocks save with no accounting category (send-guard rule)', async () => {
    const choice = { type: 'freeform', typed: 'x', isMaterial: false };
    const { getByLabelText, getByRole, findByText } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).not.toHaveBeenCalled();
    expect(await findByText(/accounting category is required/i)).toBeInTheDocument();
  });

  it('shows the base unit next to quantity for a service pick', () => {
    const choice = { type: 'service', serviceItem: {
      template_id: 11, template_name: 'CNC Routing', rate_scheme_detail: { unit_label: 'hr' } } };
    const { getByText } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByText('hr')).toBeInTheDocument();
  });
});
