import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import PriceListPicker from '@/components/PriceListPicker.svelte';
import { api } from '@/lib/api.js';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

const SERVICES = [
  { service_item_id: 1, name: 'CNC Cutting', algorithm: 'ELAPSED_TIME', rate: '90.00', unit_label: 'hr' },
  { service_item_id: 2, name: 'Design Fee', algorithm: 'FLAT_FEE', rate: '150.00', unit_label: 'ea' },
];
const INVENTORY = [
  { inventory_item_id: 10, code: 'MDF-3-4', description: '3/4 MDF sheet', selling_price: '42.00', is_catalog: true },
  { inventory_item_id: 11, code: 'LOT-XYZ', description: 'transient lot', selling_price: '5.00', is_catalog: false },
];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) =>
    Promise.resolve(url.includes('service-items') ? SERVICES : INVENTORY)
  );
});

describe('PriceListPicker', () => {
  it('lists services and catalog materials in one untagged list, excludes non-catalog', async () => {
    render(PriceListPicker, { open: true });
    expect(await screen.findByText('CNC Cutting')).toBeInTheDocument();
    expect(screen.getByText('MDF-3-4')).toBeInTheDocument();
    // non-catalog inventory is hidden
    expect(screen.queryByText('LOT-XYZ')).not.toBeInTheDocument();
    // no visible type badge on rows — picker routes by kind behind the scenes
    expect(screen.queryByText(/^service$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^material$/i)).not.toBeInTheDocument();
  });

  it('requests task-applicable services (excludes adjustments)', async () => {
    render(PriceListPicker, { open: true });
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining('task_applicable=true'))
    );
  });

  it('filters the merged list by the search box', async () => {
    render(PriceListPicker, { open: true });
    await screen.findByText('CNC Cutting');
    await fireEvent.input(screen.getByPlaceholderText(/search/i), { target: { value: 'mdf' } });
    expect(screen.queryByText('CNC Cutting')).not.toBeInTheDocument();
    expect(screen.getByText('MDF-3-4')).toBeInTheDocument();
  });

  it('emits onselect with kind+item when a row is chosen', async () => {
    const onselect = vi.fn();
    render(PriceListPicker, { open: true, onselect });
    await fireEvent.click(await screen.findByText('CNC Cutting'));
    expect(onselect).toHaveBeenCalledWith({ kind: 'service', item: expect.objectContaining({ service_item_id: 1 }) });
  });

  it('emits onfreeform for the freeform material action', async () => {
    const onfreeform = vi.fn();
    render(PriceListPicker, { open: true, onfreeform });
    await fireEvent.click(await screen.findByRole('button', { name: /freeform material/i }));
    expect(onfreeform).toHaveBeenCalled();
  });
});
