import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) => (e && e.message) || fallback || 'Request failed.',
}));
import { api } from '@/lib/api.js';
import COAddLineForm from '@/components/changeorders/COAddLineForm.svelte';

const cats = [{ id: 7, code: 'MAT', name: 'Materials' }, { id: 9, code: 'LAB', name: 'Labor' }];

const SCHEMES = [
  { rate_scheme_id: 1, name: 'CNC Routing', rate: '75.00', unit_label: 'hour', accounting_category: 9 },
  { rate_scheme_id: 2, name: 'Hand Finishing', rate: '40.00', unit_label: 'hour', accounting_category: 9 },
];

function mockNoSettings() {
  api.get.mockImplementation((url) => {
    if (url.includes('/api/rate-schemes/')) return Promise.resolve({ results: SCHEMES });
    if (url.includes('/api/settings/')) return Promise.resolve({});
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.post.mockResolvedValue({ line_item_id: 1 });
  mockNoSettings();
});

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

  it('shows the base unit next to quantity for a service pick', () => {
    const choice = { type: 'service', serviceItem: {
      template_id: 11, template_name: 'CNC Routing', rate_scheme_detail: { unit_label: 'hr' } } };
    const { getByText } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByText('hr')).toBeInTheDocument();
  });

  it('shows the base unit next to quantity for an inventory pick', () => {
    const choice = { type: 'inventory', inventoryItem: {
      inventory_item_id: 22, code: 'BOLT-14', units: 'ea' } };
    const { getByText } = render(COAddLineForm, {
      props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
    });
    expect(getByText('ea')).toBeInTheDocument();
  });

  describe('kind=material', () => {
    it('prefills description from typed and posts action add + freeform_kind material with the default AC', async () => {
      const choice = { type: 'freeform', kind: 'material', typed: 'plywood' };
      const onSaved = vi.fn();
      const { getByLabelText, getByRole } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats,
          defaultMaterialCategoryId: 7, onSaved },
      });
      expect(getByLabelText(/description/i)).toHaveValue('plywood');
      expect(getByLabelText(/accounting category/i)).toHaveValue('7');
      await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
      await fireEvent.input(getByLabelText(/price/i), { target: { value: '30' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/',
        expect.objectContaining({ action: 'add', freeform_kind: 'material', accounting_category: 7, price: '30' }));
      expect(api.post.mock.calls[0][1]).not.toHaveProperty('is_material');
      expect(onSaved).toHaveBeenCalled();
    });

    it('does not block save when no default AC is configured (backend fills it)', async () => {
      const choice = { type: 'freeform', kind: 'material', typed: 'plywood' };
      const { getByLabelText, getByRole } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats,
          defaultMaterialCategoryId: null, onSaved: vi.fn() },
      });
      await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
      await fireEvent.input(getByLabelText(/price/i), { target: { value: '30' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/',
        expect.objectContaining({ action: 'add', freeform_kind: 'material' }));
    });

    it('rejects a negative price with a field error naming Fee/Credit', async () => {
      const choice = { type: 'freeform', kind: 'material', typed: 'plywood' };
      const { getByLabelText, getByRole, findByText } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats,
          defaultMaterialCategoryId: 7, onSaved: vi.fn() },
      });
      await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '2' } });
      await fireEvent.input(getByLabelText(/price/i), { target: { value: '-5' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).not.toHaveBeenCalled();
      expect(await findByText(/fee.?credit/i)).toBeInTheDocument();
    });
  });

  describe('kind=fee', () => {
    it('defaults qty to 1, prefills description, requires AC, and posts action add + freeform_kind fee', async () => {
      const choice = { type: 'freeform', kind: 'fee', typed: 'Rush charge' };
      const onSaved = vi.fn();
      const { getByLabelText, getByRole } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved },
      });
      expect(getByLabelText(/description/i)).toHaveValue('Rush charge');
      expect(getByLabelText(/quantity/i)).toHaveValue(1);
      await fireEvent.input(getByLabelText(/amount/i), { target: { value: '50' } });
      await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '7' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/',
        expect.objectContaining({
          action: 'add', description: 'Rush charge', freeform_kind: 'fee',
          accounting_category: 7, price: '50',
        }));
      expect(onSaved).toHaveBeenCalled();
    });

    it('blocks save with no accounting category', async () => {
      const choice = { type: 'freeform', kind: 'fee', typed: 'x' };
      const { getByLabelText, getByRole, findByText } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
      });
      await fireEvent.input(getByLabelText(/amount/i), { target: { value: '50' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).not.toHaveBeenCalled();
      expect(await findByText(/accounting category is required/i)).toBeInTheDocument();
    });

    it('allows a negative amount and shows a credit note', async () => {
      const choice = { type: 'freeform', kind: 'fee', typed: 'Refund' };
      const onSaved = vi.fn();
      const { getByLabelText, getByRole, findByText } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved },
      });
      await fireEvent.input(getByLabelText(/amount/i), { target: { value: '-25' } });
      expect(await findByText(/appear as a credit/i)).toBeInTheDocument();
      await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '7' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/',
        expect.objectContaining({ action: 'add', freeform_kind: 'fee', price: '-25' }));
      expect(onSaved).toHaveBeenCalled();
    });

    it('rejects a zero amount with a field error, mirroring FeeModal', async () => {
      const choice = { type: 'freeform', kind: 'fee', typed: 'Free sample' };
      const { getByLabelText, getByRole, findByText } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
      });
      await fireEvent.input(getByLabelText(/amount/i), { target: { value: '0' } });
      await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '7' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).not.toHaveBeenCalled();
      expect(await findByText(/must not have a zero price/i)).toBeInTheDocument();
    });

    it('rejects an empty amount as zero for a fee line', async () => {
      const choice = { type: 'freeform', kind: 'fee', typed: 'Free sample' };
      const { getByLabelText, getByRole, findByText } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
      });
      await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '7' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).not.toHaveBeenCalled();
      expect(await findByText(/must not have a zero price/i)).toBeInTheDocument();
    });
  });

  describe('kind=work', () => {
    it('loads task-applicable rate schemes and offers them as a preset dropdown', async () => {
      const choice = { type: 'freeform', kind: 'work', typed: 'Custom milling' };
      const { findByRole } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
      });
      const select = await findByRole('combobox', { name: /preset/i });
      expect(select).toBeInTheDocument();
      expect(await findByRole('option', { name: 'CNC Routing' })).toBeInTheDocument();
    });

    it('preselects the configured default preset when it is in the list, and stamps its fields', async () => {
      api.get.mockImplementation((url) => {
        if (url.includes('/api/rate-schemes/')) return Promise.resolve({ results: SCHEMES });
        if (url.includes('/api/settings/')) return Promise.resolve({ default_rate_scheme: '2' });
        return Promise.resolve({});
      });
      const choice = { type: 'freeform', kind: 'work', typed: 'Custom milling' };
      const { findByRole, getByLabelText } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
      });
      await findByRole('option', { name: 'Hand Finishing' });
      const select = await findByRole('combobox', { name: /preset/i });
      expect(select).toHaveValue('2');
      expect(await findByRole('spinbutton', { name: /rate/i })).toHaveValue(40);
      expect(getByLabelText(/accounting category/i)).toHaveValue('9');
    });

    it('does not preselect a default that is absent from the list', async () => {
      api.get.mockImplementation((url) => {
        if (url.includes('/api/rate-schemes/')) return Promise.resolve({ results: SCHEMES });
        if (url.includes('/api/settings/')) return Promise.resolve({ default_rate_scheme: '999' });
        return Promise.resolve({});
      });
      const choice = { type: 'freeform', kind: 'work', typed: 'Custom milling' };
      const { findByRole } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
      });
      const select = await findByRole('combobox', { name: /preset/i });
      expect(select).toHaveValue('');
    });

    it('picking a preset stamps rate/units/AC into editable fields, then submits plain values (no scheme id)', async () => {
      const choice = { type: 'freeform', kind: 'work', typed: 'Custom milling' };
      const onSaved = vi.fn();
      const { findByRole, getByLabelText, getByRole } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved },
      });
      const select = await findByRole('combobox', { name: /preset/i });
      await fireEvent.change(select, { target: { value: '1' } });
      expect(getByLabelText(/rate/i)).toHaveValue(75);
      expect(getByLabelText(/accounting category/i)).toHaveValue('9');
      // User edits the stamped rate before submitting.
      await fireEvent.input(getByLabelText(/rate/i), { target: { value: '80' } });
      await fireEvent.input(getByLabelText(/quantity/i), { target: { value: '4' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).toHaveBeenCalledWith('/api/change-orders/42/line-items/', {
        action: 'add', description: 'Custom milling', qty: '4', units: 'hour', price: '80',
        accounting_category: 9, freeform_kind: 'work',
      });
      expect(onSaved).toHaveBeenCalled();
    });

    it('requires an accounting category', async () => {
      const choice = { type: 'freeform', kind: 'work', typed: 'Custom milling' };
      const { getByLabelText, getByRole, findByText } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
      });
      await fireEvent.input(getByLabelText(/rate/i), { target: { value: '50' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).not.toHaveBeenCalled();
      expect(await findByText(/accounting category is required/i)).toBeInTheDocument();
    });

    it('rejects a negative rate with a field error naming Fee/Credit', async () => {
      const choice = { type: 'freeform', kind: 'work', typed: 'Custom milling' };
      const { getByLabelText, getByRole, findByText } = render(COAddLineForm, {
        props: { open: true, choice, coId: 42, categories: cats, onSaved: vi.fn() },
      });
      await fireEvent.input(getByLabelText(/rate/i), { target: { value: '-10' } });
      await fireEvent.change(getByLabelText(/accounting category/i), { target: { value: '9' } });
      await fireEvent.click(getByRole('button', { name: /add/i }));
      expect(api.post).not.toHaveBeenCalled();
      expect(await findByText(/fee.?credit/i)).toBeInTheDocument();
    });
  });
});
