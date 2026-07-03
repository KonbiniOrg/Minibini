import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import PriceListPicker from '@/components/PriceListPicker.svelte';

const SVC_ITEM = {
  template_id: 11, template_name: 'CNC Routing', description: 'Router pass',
  rate_scheme: 5,
  rate_scheme_detail: { rate_scheme_id: 5, name: 'Machine time', rate: '75.00', unit_label: 'hr' },
};
const INV_ITEM = {
  inventory_item_id: 22, code: 'BOLT-14', description: 'Hex bolt',
  selling_price: '0.50', units: 'ea', is_catalog: true, is_active: true,
};

function mockApiForQuery() {
  api.get.mockImplementation((url) => {
    if (url.includes('/api/service-items/')) return Promise.resolve({ results: [SVC_ITEM], count: 1 });
    if (url.includes('/api/inventory/')) return Promise.resolve({ results: [INV_ITEM], count: 1 });
    return Promise.resolve({ results: [], count: 0 });
  });
}
const baseProps = () => ({ open: true, onChoose: vi.fn(), onclose: vi.fn() });

beforeEach(() => { api.get.mockReset(); });

describe('PriceListPicker (onChoose emitter)', () => {
  it('fetches nothing and shows no list before typing', () => {
    api.get.mockResolvedValue({ results: [], count: 0 });
    const { queryByRole } = render(PriceListPicker, { props: baseProps() });
    expect(api.get).not.toHaveBeenCalled();
    expect(queryByRole('listbox')).toBeNull();
  });

  it('searches both catalogs after typing (past debounce)', async () => {
    mockApiForQuery();
    const { getByPlaceholderText, findByText } = render(PriceListPicker, { props: baseProps() });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'cnc' } });
    expect(await findByText('CNC Routing')).toBeInTheDocument();
    expect(await findByText('BOLT-14')).toBeInTheDocument();
    const invCall = api.get.mock.calls.find((c) => c[0].includes('/api/inventory/'));
    expect(invCall[0]).toContain('is_catalog=true');
    expect(invCall[0]).toContain('search=cnc');
  });

  it('emits {type:service, serviceItem} when a service row is picked', async () => {
    mockApiForQuery();
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'cnc' } });
    await fireEvent.mouseDown(await findByRole('button', { name: /CNC Routing/ }));
    expect(props.onChoose).toHaveBeenCalledWith({
      type: 'service',
      serviceItem: expect.objectContaining({ template_id: 11 }),
    });
  });

  it('emits {type:inventory, inventoryItem} when an inventory row is picked', async () => {
    mockApiForQuery();
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'bolt' } });
    await fireEvent.mouseDown(await findByRole('button', { name: /BOLT-14/ }));
    expect(props.onChoose).toHaveBeenCalledWith({
      type: 'inventory',
      inventoryItem: expect.objectContaining({ inventory_item_id: 22 }),
    });
  });

  it('freeform commit defaults to a fee (isMaterial false)', async () => {
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'Rush charge' } });
    await fireEvent.click(await findByRole('button', { name: /add line/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', typed: 'Rush charge', isMaterial: false });
  });

  it('freeform commit with the material checkbox set emits isMaterial true', async () => {
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: '3/4 plywood' } });
    await fireEvent.click(await findByRole('checkbox', { name: /material/i }));
    await fireEvent.click(await findByRole('button', { name: /add line/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', typed: '3/4 plywood', isMaterial: true });
  });

  it('clears typed text and the material toggle when reopened', async () => {
    const props = baseProps();
    const { getByPlaceholderText, getByRole, rerender } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'partial typing' } });
    await fireEvent.click(getByRole('checkbox', { name: /material/i }));
    expect(getByPlaceholderText(/search/i)).toHaveValue('partial typing');
    // Cancel (close), then reopen — the picker must start fresh.
    await rerender({ ...props, open: false });
    await rerender({ ...props, open: true });
    expect(getByPlaceholderText(/search/i)).toHaveValue('');
    expect(getByRole('checkbox', { name: /material/i })).not.toBeChecked();
  });

  it('shows the material checkbox and Add Line button constantly, from the start', async () => {
    const props = baseProps();
    const { getByRole } = render(PriceListPicker, { props });
    // Constant affordances — present before anything is typed, label never changes.
    expect(getByRole('checkbox', { name: /material/i })).toBeInTheDocument();
    const addBtn = getByRole('button', { name: /add line/i });
    expect(addBtn).toBeInTheDocument();
    // Clicking with nothing typed still emits a freeform commit (empty typed).
    await fireEvent.click(addBtn);
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', typed: '', isMaterial: false });
  });
});
