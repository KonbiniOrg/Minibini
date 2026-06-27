import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import PlanMaterialModal from '@/components/PlanMaterialModal.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue([]);
  api.post.mockResolvedValue({});
});

const INVENTORY_ITEM = {
  inventory_item_id: 10,
  code: 'MDF-3-4',
  description: '3/4 MDF sheet',
  units: 'sheet',
  selling_price: '42.00',
  purchase_price: '30.00',
  accounting_category: null,
  is_catalog: true,
};

describe('PlanMaterialModal', () => {
  it('creates a freeform plan material on a plan task', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(PlanMaterialModal, {
      props: { open: true, mode: 'create', planTaskId: 4, onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Steel' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '3' } });
    await fireEvent.input(getByLabelText(/Unit Cost/), { target: { value: '5' } });
    await fireEvent.input(getByLabelText(/Sell Price/), { target: { value: '8' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/plan-tasks/4/materials/', {
      description: 'Steel', quantity: 3, units: 'none', unit_cost: 5, sell_price: 8,
      inventory_item: null, accounting_category: null,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  describe('with a pre-selected inventoryItem', () => {
    it('pre-fills description from the catalog item', async () => {
      render(PlanMaterialModal, {
        props: { open: true, worksheetId: 5, inventoryItem: INVENTORY_ITEM },
      });
      expect(await screen.findByDisplayValue('3/4 MDF sheet')).toBeInTheDocument();
    });

    it('hides the internal InventoryItemPicker when inventoryItem is provided', async () => {
      render(PlanMaterialModal, {
        props: { open: true, worksheetId: 5, inventoryItem: INVENTORY_ITEM },
      });
      expect(screen.queryByPlaceholderText(/search inventory/i)).not.toBeInTheDocument();
    });

    it('pre-fills sell price from selling_price', async () => {
      render(PlanMaterialModal, {
        props: { open: true, worksheetId: 5, inventoryItem: INVENTORY_ITEM },
      });
      expect(await screen.findByDisplayValue('42.00')).toBeInTheDocument();
    });

    it('pre-fills unit cost from purchase_price', async () => {
      render(PlanMaterialModal, {
        props: { open: true, worksheetId: 5, inventoryItem: INVENTORY_ITEM },
      });
      expect(await screen.findByDisplayValue('30.00')).toBeInTheDocument();
    });
  });
});
