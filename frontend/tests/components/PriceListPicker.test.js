import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import PriceListPicker from '@/components/PriceListPicker.svelte';

const SVC_ITEM = {
  rate_scheme_id: 11,
  name: 'CNC Routing',
  description: 'Router pass',
  algorithm: 'elapsed_time',
  rate: '75.00',
  unit_label: 'hr',
};

const INV_ITEM = {
  inventory_item_id: 22,
  code: 'BOLT-14',
  description: 'Hex bolt',
  selling_price: '0.50',
  units: 'ea',
  is_catalog: true,
  is_active: true,
};

function mockApiForQuery() {
  api.get.mockImplementation((url) => {
    if (url.includes('/api/rate-schemes/')) {
      return Promise.resolve({ results: [SVC_ITEM], count: 1 });
    }
    if (url.includes('/api/inventory/')) {
      return Promise.resolve({ results: [INV_ITEM], count: 1 });
    }
    return Promise.resolve({ results: [], count: 0 });
  });
}

beforeEach(() => { api.get.mockReset(); });

describe('PriceListPicker', () => {
  it('renders nothing fetched or shown before typing', async () => {
    api.get.mockResolvedValue({ results: [], count: 0 });
    const { queryByText, queryByRole } = render(PriceListPicker, {
      props: { open: true, onselect: vi.fn(), onfreeform: vi.fn(), onclose: vi.fn() },
    });
    // No results shown and no API calls made before the user types anything
    expect(api.get).not.toHaveBeenCalled();
    expect(queryByText('CNC Routing')).toBeNull();
    expect(queryByText('BOLT-14')).toBeNull();
    expect(queryByRole('listbox')).toBeNull();
  });

  it('shows service and material results after typing (waits past debounce)', async () => {
    mockApiForQuery();
    const { getByPlaceholderText, findByText } = render(PriceListPicker, {
      props: { open: true, onselect: vi.fn(), onfreeform: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'cnc' } });
    // findByText polls until the element appears (waits past the 250ms debounce)
    expect(await findByText('CNC Routing')).toBeInTheDocument();
    expect(await findByText('BOLT-14')).toBeInTheDocument();
  });

  it('shows each row unit to the right of the price', async () => {
    mockApiForQuery();
    const { getByPlaceholderText, findByText } = render(PriceListPicker, {
      props: { open: true, onselect: vi.fn(), onfreeform: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'c' } });
    expect(await findByText('/ hr')).toBeInTheDocument();
    expect(await findByText('/ ea')).toBeInTheDocument();
  });

  it('calls rate-schemes with task_applicable=true and search param', async () => {
    mockApiForQuery();
    const { getByPlaceholderText } = render(PriceListPicker, {
      props: { open: true, onselect: vi.fn(), onfreeform: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'bolt' } });
    await new Promise((r) => setTimeout(r, 300));
    const svcCalls = api.get.mock.calls.filter((c) => c[0].includes('/api/rate-schemes/'));
    expect(svcCalls.length).toBeGreaterThan(0);
    expect(svcCalls[0][0]).toContain('task_applicable=true');
    expect(svcCalls[0][0]).toContain('search=bolt');
  });

  it('calls inventory with is_active=true, is_catalog=true and search param', async () => {
    mockApiForQuery();
    const { getByPlaceholderText } = render(PriceListPicker, {
      props: { open: true, onselect: vi.fn(), onfreeform: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'bolt' } });
    await new Promise((r) => setTimeout(r, 300));
    const invCalls = api.get.mock.calls.filter((c) => c[0].includes('/api/inventory/'));
    expect(invCalls.length).toBeGreaterThan(0);
    expect(invCalls[0][0]).toContain('is_active=true');
    expect(invCalls[0][0]).toContain('is_catalog=true');
    expect(invCalls[0][0]).toContain('search=bolt');
  });

  it('emits onselect with {kind, item} when a service row is picked via mousedown', async () => {
    mockApiForQuery();
    const onselect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, {
      props: { open: true, onselect, onfreeform: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'cnc' } });
    const btn = await findByRole('button', { name: /CNC Routing/ });
    await fireEvent.mouseDown(btn);
    expect(onselect).toHaveBeenCalledWith({
      kind: 'service',
      item: expect.objectContaining({ rate_scheme_id: 11, name: 'CNC Routing' }),
    });
  });

  it('emits onselect with {kind:material, item} when an inventory row is picked', async () => {
    mockApiForQuery();
    const onselect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, {
      props: { open: true, onselect, onfreeform: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'bolt' } });
    const btn = await findByRole('button', { name: /BOLT-14/ });
    await fireEvent.mouseDown(btn);
    expect(onselect).toHaveBeenCalledWith({
      kind: 'material',
      item: expect.objectContaining({ inventory_item_id: 22, code: 'BOLT-14' }),
    });
  });

  it('emits onfreeform when the freeform footer button is clicked', async () => {
    const onfreeform = vi.fn();
    const { findByText } = render(PriceListPicker, {
      props: { open: true, onselect: vi.fn(), onfreeform, onclose: vi.fn() },
    });
    const btn = await findByText(/freeform/i);
    await fireEvent.click(btn);
    expect(onfreeform).toHaveBeenCalled();
  });

  it('does not render when open=false', () => {
    const { queryByText } = render(PriceListPicker, {
      props: { open: false, onselect: vi.fn(), onfreeform: vi.fn(), onclose: vi.fn() },
    });
    expect(queryByText(/Add item/)).toBeNull();
  });
});
