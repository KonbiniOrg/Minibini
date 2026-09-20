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

  it('service choice prefills description from template_name and omits it untouched', async () => {
    const choice = { type: 'service', serviceItem: { template_id: 11, template_name: 'CNC Routing' } };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByLabelText(/description/i)).toHaveValue('CNC Routing');
    await fireEvent.click(getByRole('button', { name: /add/i }));
    const [, payload] = api.post.mock.calls.at(-1);
    expect('description' in payload).toBe(false);
  });

  it('service choice sends an edited description as an override', async () => {
    const choice = { type: 'service', serviceItem: { template_id: 11, template_name: 'CNC Routing' } };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/description/i), { target: { value: 'CNC Routing (rush)' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items-from-service/',
      expect.objectContaining({ description: 'CNC Routing (rush)' }));
  });

  it('inventory choice prefills description from the PLI and omits it untouched', async () => {
    const choice = { type: 'inventory', inventoryItem: { inventory_item_id: 22, code: 'BOLT-14', description: 'Steel bolt 1/4"' } };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByLabelText(/description/i)).toHaveValue('Steel bolt 1/4"');
    await fireEvent.click(getByRole('button', { name: /add/i }));
    const [, payload] = api.post.mock.calls.at(-1);
    expect('description' in payload).toBe(false);
  });

  it('inventory choice sends an edited description as an override', async () => {
    const choice = { type: 'inventory', inventoryItem: { inventory_item_id: 22, code: 'BOLT-14', description: 'Steel bolt 1/4"' } };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/description/i), { target: { value: 'Steel bolt, zinc-plated' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      expect.objectContaining({ description: 'Steel bolt, zinc-plated' }));
  });

  it('re-picking a different choice reseeds the description field', async () => {
    const choice1 = { type: 'inventory', inventoryItem: { inventory_item_id: 22, code: 'BOLT-14', description: 'Steel bolt' } };
    const { getByLabelText, rerender } = render(EstimateAddLineForm, {
      props: { open: true, choice: choice1, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByLabelText(/description/i)).toHaveValue('Steel bolt');
    await fireEvent.input(getByLabelText(/description/i), { target: { value: 'Custom edit' } });
    const choice2 = { type: 'inventory', inventoryItem: { inventory_item_id: 23, code: 'NUT-14', description: 'Steel nut' } };
    await rerender({ open: true, choice: choice2, estimateId: 42, categories: cats, onSaved: vi.fn() });
    expect(getByLabelText(/description/i)).toHaveValue('Steel nut');
  });

  it('freeform line posts a manual payload without is_material; description prefilled from typed', async () => {
    // RM 2026-08-11: material-ness derives server-side from the chosen AC —
    // the form never sends is_material.
    const choice = { type: 'freeform', typed: 'Rush charge' };
    const { getByLabelText, getByRole } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByLabelText(/description/i)).toHaveValue('Rush charge');
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/price/i), { target: { value: '50' } });
    await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/42/line-items/',
      expect.objectContaining({ description: 'Rush charge', accounting_category: 7, price: '50' }));
    const [, payload] = api.post.mock.calls.at(-1);
    expect('is_material' in payload).toBe(false);
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

  it('freeform line blocks save with no accounting category (hand-line rule, no material exemption)', async () => {
    const choice = { type: 'freeform', typed: 'x' };
    const { getByLabelText, getByRole, findByText } = render(EstimateAddLineForm, {
      props: { open: true, choice, estimateId: 42, categories: cats, onSaved: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).not.toHaveBeenCalled();
    expect(await findByText(/accounting category is required/i)).toBeInTheDocument();
  });
});
