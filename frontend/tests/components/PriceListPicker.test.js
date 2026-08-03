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
  selling_price: '0.50', units: 'ea', is_active: true,
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
    expect(invCall[0]).toContain('is_active=true');
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

  it('emits {type:freeform, kind:work} from the Add Work button', async () => {
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'Custom milling' } });
    await fireEvent.click(await findByRole('button', { name: /add work/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', kind: 'work', typed: 'Custom milling' });
  });

  it('emits {type:freeform, kind:material} from the Add Material button', async () => {
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: '3/4 plywood' } });
    await fireEvent.click(await findByRole('button', { name: /add material/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', kind: 'material', typed: '3/4 plywood' });
  });

  it('emits {type:freeform, kind:fee} from the Add Fee-Credit button', async () => {
    const props = baseProps();
    const { getByPlaceholderText, findByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'Rush charge' } });
    await fireEvent.click(await findByRole('button', { name: /add fee-credit/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', kind: 'fee', typed: 'Rush charge' });
  });

  it('clears typed text when reopened', async () => {
    const props = baseProps();
    const { getByPlaceholderText, rerender } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'partial typing' } });
    expect(getByPlaceholderText(/search/i)).toHaveValue('partial typing');
    // Cancel (close), then reopen — the picker must start fresh.
    await rerender({ ...props, open: false });
    await rerender({ ...props, open: true });
    expect(getByPlaceholderText(/search/i)).toHaveValue('');
  });

  it('does not offer Add Task by default (estimate surface)', () => {
    const { queryByRole } = render(PriceListPicker, { props: baseProps() });
    expect(queryByRole('button', { name: /add task/i })).toBeNull();
  });

  it('task surface offers explicit Task/Material/Fee buttons (no checkbox/Add Line)', async () => {
    const props = { ...baseProps(), taskSurface: true };
    const { getByPlaceholderText, getByRole, queryByRole } = render(PriceListPicker, { props });
    await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'Custom milling' } });
    expect(queryByRole('button', { name: /add line/i })).toBeNull();
    expect(queryByRole('checkbox')).toBeNull();
    await fireEvent.click(getByRole('button', { name: /add task/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform-task', typed: 'Custom milling' });
    await fireEvent.click(getByRole('button', { name: /add material/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', typed: 'Custom milling', isMaterial: true });
    await fireEvent.click(getByRole('button', { name: /add fee/i }));
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', typed: 'Custom milling', isMaterial: false });
  });

  it('labels the task-surface fee button "Add Fee / Credit"', () => {
    const props = { ...baseProps(), taskSurface: true };
    const { getByRole } = render(PriceListPicker, { props });
    expect(getByRole('button', { name: 'Add Fee / Credit' })).toBeInTheDocument();
  });

  it('shows the Work/Material/Fee-Credit buttons constantly, from the start', async () => {
    const props = baseProps();
    const { getByRole } = render(PriceListPicker, { props });
    // Constant affordances — present before anything is typed, labels never change.
    expect(getByRole('button', { name: /add work/i })).toBeInTheDocument();
    expect(getByRole('button', { name: /add material/i })).toBeInTheDocument();
    const feeBtn = getByRole('button', { name: /add fee-credit/i });
    expect(feeBtn).toBeInTheDocument();
    // Clicking with nothing typed still emits a freeform commit (empty typed).
    await fireEvent.click(feeBtn);
    expect(props.onChoose).toHaveBeenCalledWith({ type: 'freeform', kind: 'fee', typed: '' });
  });
});
