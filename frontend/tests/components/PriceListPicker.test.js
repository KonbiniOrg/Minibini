import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import PriceListPicker from '@/components/PriceListPicker.svelte';

// A saved-work ServiceItem (the Add Line "service" source), priced via its RateScheme.
const SVC_ITEM = {
  template_id: 11,
  template_name: 'CNC Routing',
  description: 'Router pass',
  rate_scheme: 5,
  rate_scheme_detail: { rate_scheme_id: 5, name: 'Machine time', rate: '75.00', unit_label: 'hr', algorithm: 'elapsed_time' },
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
    if (url.includes('/api/service-items/')) {
      return Promise.resolve({ results: [SVC_ITEM], count: 1 });
    }
    if (url.includes('/api/inventory/')) {
      return Promise.resolve({ results: [INV_ITEM], count: 1 });
    }
    return Promise.resolve({ results: [], count: 0 });
  });
}

const baseProps = () => ({
  open: true, onselect: vi.fn(), oncustomtask: vi.fn(), onfreeform: vi.fn(), onclose: vi.fn(),
});

beforeEach(() => { api.get.mockReset(); });

describe('PriceListPicker', () => {
  it('renders nothing fetched or shown before typing', async () => {
    api.get.mockResolvedValue({ results: [], count: 0 });
    const { queryByText, queryByRole } = render(PriceListPicker, { props: baseProps() });
    expect(api.get).not.toHaveBeenCalled();
    expect(queryByText('CNC Routing')).toBeNull();
    expect(queryByText('BOLT-14')).toBeNull();
    expect(queryByRole('listbox')).toBeNull();
  });

  it('shows saved-work and material results after typing (waits past debounce)', async () => {
    mockApiForQuery();
    const { getByPlaceholderText, findByText } = render(PriceListPicker, { props: baseProps() });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'cnc' } });
    expect(await findByText('CNC Routing')).toBeInTheDocument();
    expect(await findByText('BOLT-14')).toBeInTheDocument();
  });

  it('shows each row unit to the right of the price', async () => {
    mockApiForQuery();
    const { getByPlaceholderText, findByText } = render(PriceListPicker, { props: baseProps() });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'c' } });
    expect(await findByText('/ hr')).toBeInTheDocument();
    expect(await findByText('/ ea')).toBeInTheDocument();
  });

  it('searches the saved-work catalog (service-items) with the search param', async () => {
    mockApiForQuery();
    const { getByPlaceholderText } = render(PriceListPicker, { props: baseProps() });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'bolt' } });
    await new Promise((r) => setTimeout(r, 300));
    const svcCalls = api.get.mock.calls.filter((c) => c[0].includes('/api/service-items/'));
    expect(svcCalls.length).toBeGreaterThan(0);
    expect(svcCalls[0][0]).toContain('search=bolt');
  });

  it('calls inventory with is_active=true, is_catalog=true and search param', async () => {
    mockApiForQuery();
    const { getByPlaceholderText } = render(PriceListPicker, { props: baseProps() });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'bolt' } });
    await new Promise((r) => setTimeout(r, 300));
    const invCalls = api.get.mock.calls.filter((c) => c[0].includes('/api/inventory/'));
    expect(invCalls.length).toBeGreaterThan(0);
    expect(invCalls[0][0]).toContain('is_active=true');
    expect(invCalls[0][0]).toContain('is_catalog=true');
    expect(invCalls[0][0]).toContain('search=bolt');
  });

  it('emits onselect with {kind:service, the ServiceItem} when a saved-work row is picked', async () => {
    mockApiForQuery();
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'cnc' } });
    const btn = await findByRole('button', { name: /CNC Routing/ });
    await fireEvent.mouseDown(btn);
    expect(props.onselect).toHaveBeenCalledWith({
      kind: 'service',
      item: expect.objectContaining({ template_id: 11, template_name: 'CNC Routing' }),
    });
  });

  it('emits onselect with {kind:material, item} when an inventory row is picked', async () => {
    mockApiForQuery();
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'bolt' } });
    const btn = await findByRole('button', { name: /BOLT-14/ });
    await fireEvent.mouseDown(btn);
    expect(props.onselect).toHaveBeenCalledWith({
      kind: 'material',
      item: expect.objectContaining({ inventory_item_id: 22, code: 'BOLT-14' }),
    });
  });

  it('emits oncustomtask when the custom-task footer button is clicked', async () => {
    const props = baseProps();
    const { findByText } = render(PriceListPicker, { props });
    const btn = await findByText(/custom task/i);
    await fireEvent.click(btn);
    expect(props.oncustomtask).toHaveBeenCalled();
  });

  it('emits onfreeform when the freeform footer button is clicked', async () => {
    const props = baseProps();
    const { findByText } = render(PriceListPicker, { props });
    const btn = await findByText(/freeform/i);
    await fireEvent.click(btn);
    expect(props.onfreeform).toHaveBeenCalled();
  });

  it('does not render when open=false', () => {
    const { queryByText } = render(PriceListPicker, { props: { ...baseProps(), open: false } });
    expect(queryByText(/Add item/)).toBeNull();
  });
});
