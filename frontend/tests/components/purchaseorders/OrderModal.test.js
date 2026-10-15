// frontend/tests/components/purchaseorders/OrderModal.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, f) => e?.message || f,
}));
vi.mock('@/stores/messages.js', () => ({ showSuccess: vi.fn(), showError: vi.fn() }));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import { showSuccess } from '@/stores/messages.js';
import OrderModal from '@/components/purchaseorders/OrderModal.svelte';

const ITEM = { inventory_item_id: 7, code: 'BB34P', description: '3/4 Baltic Birch', units: 'sheet',
  purchase_price: '60.00', accounting_category: 3 };
const HISTORY = {
  vendors: [
    { business_id: 17, business_name: 'Rugby Architectural', contact_id: 88, last_ordered: '2026-08-02',
      last_price: '62.40', vendor_sku: 'BB34P-48', po_number: 'PO0120', times: 6 },
    { business_id: 59, business_name: 'Royal Plywood', contact_id: 98, last_ordered: '2026-07-09',
      last_price: '73.33', vendor_sku: 'RP-77', po_number: 'PO0012', times: 1 },
  ],
  earmarks: [{ job_id: 48, job_number: '08149', quantity: '3.00' }],
  open_drafts: [
    { po_id: 131, po_number: 'PO0131', business_id: 17, business_name: 'Rugby Architectural', line_count: 2 },
    { po_id: 132, po_number: 'PO0132', business_id: null, business_name: null, line_count: 0 },
  ],
};
const CONTACTS = {
  17: [{ contact_id: 88, first_name: 'Ann', last_name: 'Rugby' }, { contact_id: 89, first_name: 'Bob', last_name: 'Rugby' }],
  59: [{ contact_id: 98, first_name: 'Denis', last_name: 'Schneider' }],
};
const MATERIAL = { material_id: 55, job: 39, description: 'ply for cabinets', quantity: '4', units: 'sheet',
  unit_cost: '60.00', accounting_category: 3, inventory_item: 7, item_code: 'BB34P', qty_on_hand: '0',
  po_line_item_id: null, consumption_state: 'pending', cost_source: 'entered' };

function mockApi({ history = HISTORY } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/inventory/7/') return Promise.resolve(ITEM);
    if (url.startsWith('/api/inventory/7/vendor-history/')) return Promise.resolve(history);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [{ id: 3, name: 'Materials' }] });
    if (url.startsWith('/api/contacts/?business=')) {
      const id = Number(new URL('http://x' + url).searchParams.get('business'));
      return Promise.resolve({ results: CONTACTS[id] || [] });
    }
    if (url.startsWith('/api/businesses/')) return Promise.resolve({ business_id: 5, business_name: 'Acme', default_contact: 9 });
    if (url.startsWith('/api/units')) return Promise.resolve(['none', 'sheet', 'ea']);
    return Promise.resolve([]);
  });
}

beforeEach(() => {
  mockApi();
  api.post.mockReset();
  api.post.mockResolvedValue({ po_id: 200, po_number: 'PO0200', line_item_id: 9 });
  showSuccess.mockReset();
  push.mockReset();
});

describe('OrderModal — material source', () => {
  it('seeds vendor, contact, SKU, price and qty from history and the material; item is read-only', async () => {
    const { findByRole, getByLabelText, getByText, queryByPlaceholderText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    expect((await findByRole('combobox', { name: /Vendor/ })).value).toBe('17');
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('88'));
    expect(getByLabelText(/Vendor SKU/).value).toBe('BB34P-48');
    expect(getByLabelText(/^Price/).value).toBe('62.40');
    expect(getByLabelText(/^Qty/).value).toBe('4');
    expect(getByText('BB34P')).toBeInTheDocument();
    expect(queryByPlaceholderText('Search inventory items…')).toBeNull();
    expect(getByText(/Also needed: 08149 ×3/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/inventory/7/vendor-history/?exclude_job=39');
  });

  it('offers the vendor\'s open draft as an explicit choice; Submit is disabled until chosen', async () => {
    const { findByRole, getByRole, getByLabelText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    const addTo = await findByRole('radio', { name: /Add to PO0131 \(2 lines\)/ });
    expect(getByRole('radio', { name: /Start a new PO/ })).not.toBeChecked();
    expect(addTo).not.toBeChecked();
    expect(getByRole('button', { name: 'Create PO' })).toBeDisabled();
    await fireEvent.click(addTo);
    expect(getByRole('button', { name: 'Add to PO0131' })).toBeEnabled();
    // The draft already has a contact and date: those fields collapse.
    expect(() => getByLabelText(/Contact/)).toThrow();
    await fireEvent.click(getByRole('button', { name: 'Add to PO0131' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/55/order/', {
      po_id: 131,
      line: { qty: '4', units: 'sheet', price: '62.40', description: 'ply for cabinets',
              vendor_sku: 'BB34P-48', accounting_category: 3 },
    }));
  });

  it('vendor-less drafts are never offered; Create PO posts the po block and navigates', async () => {
    const onDone = vi.fn();
    const { findByRole, getByRole, queryByRole, getByLabelText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone, onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await findByRole('radio', { name: /Add to PO0131/ });
    expect(queryByRole('radio', { name: /PO0132/ })).toBeNull();
    await fireEvent.click(getByRole('radio', { name: /Start a new PO/ }));
    await fireEvent.input(getByLabelText(/Requested date/), { target: { value: '2026-10-20' } });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/55/order/', {
      po: { business: 17, contact: 88, requested_date: '2026-10-20' },
      line: expect.objectContaining({ qty: '4', vendor_sku: 'BB34P-48' }),
    }));
    expect(showSuccess).toHaveBeenCalledWith('Added to', { href: '#/purchase-orders/200', label: 'PO0200' });
    expect(onDone).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/purchase-orders/200');
  });

  it('switching vendor re-seeds SKU/price unless the SKU was hand-edited; no draft → no choice needed', async () => {
    const { findByRole, getByRole, getByLabelText, queryByRole } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    const vendor = await findByRole('combobox', { name: /Vendor/ });
    await fireEvent.change(vendor, { target: { value: '59' } });
    await waitFor(() => expect(getByLabelText(/Vendor SKU/).value).toBe('RP-77'));
    expect(getByLabelText(/^Price/).value).toBe('73.33');
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('98'));
    expect(queryByRole('radio')).toBeNull();                 // Royal has no open draft
    expect(getByRole('button', { name: 'Create PO' })).toBeEnabled();
    await fireEvent.input(getByLabelText(/Vendor SKU/), { target: { value: 'MINE-1' } });
    await fireEvent.change(vendor, { target: { value: '17' } });
    await waitFor(() => expect(getByLabelText(/^Price/).value).toBe('62.40'));
    expect(getByLabelText(/Vendor SKU/).value).toBe('MINE-1');
  });

  it('a search-picked vendor gets no history SKU/price: line defaults return', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/businesses/?search=')) return Promise.resolve({ results: [{ business_id: 5, business_name: 'Acme Steel', default_contact: 9 }] });
      if (url === '/api/businesses/5/') return Promise.resolve({ business_id: 5, business_name: 'Acme Steel', default_contact: 9 });
      if (url.startsWith('/api/contacts/?business=5')) return Promise.resolve({ results: [{ contact_id: 9, first_name: 'Sam', last_name: 'Acme' }] });
      if (url === '/api/inventory/7/') return Promise.resolve(ITEM);
      if (url.startsWith('/api/inventory/7/vendor-history/')) return Promise.resolve(HISTORY);
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [{ id: 3, name: 'Materials' }] });
      if (url.startsWith('/api/contacts/?business=')) {
        const id = Number(new URL('http://x' + url).searchParams.get('business'));
        return Promise.resolve({ results: CONTACTS[id] || [] });
      }
      if (url.startsWith('/api/businesses/')) return Promise.resolve({ business_id: 5, default_contact: 9 });
      return Promise.resolve([]);
    });
    const { findByRole, getByLabelText, findByPlaceholderText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    const vendor = await findByRole('combobox', { name: /Vendor/ });
    await waitFor(() => expect(getByLabelText(/Vendor SKU/).value).toBe('BB34P-48'));
    expect(getByLabelText(/^Price/).value).toBe('62.40');
    await fireEvent.change(vendor, { target: { value: '__search' } });
    const search = await findByPlaceholderText('Search business…');
    await fireEvent.input(search, { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /Acme Steel/ }));
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('9'));
    expect(getByLabelText(/Vendor SKU/).value).toBe('');
    expect(getByLabelText(/^Price/).value).toBe('60.00');
  });

  it('a contact_id from history that is no longer at the business falls back to the first contact', async () => {
    mockApi({ history: { ...HISTORY, vendors: [{ ...HISTORY.vendors[0], contact_id: 999 }] } });
    const { findByRole, getByLabelText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('88'));
  });

  it('shows a top-level business error under the vendor picker and keeps the form', async () => {
    mockApi({ history: { ...HISTORY, open_drafts: [] } });
    api.post.mockRejectedValue({ status: 400, data: { business: ['Rugby Architectural is inactive.'] } });
    const { findByRole, getByRole, findByText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    expect(await findByText('Rugby Architectural is inactive.')).toBeInTheDocument();
    expect(getByRole('button', { name: 'Create PO' })).toBeEnabled();
    expect(push).not.toHaveBeenCalled();
  });

  it('nested po.* and line.* errors land under their inputs; non_field_errors in the footer', async () => {
    mockApi({ history: { ...HISTORY, open_drafts: [] } });
    api.post.mockRejectedValue({ status: 400, data: {
      po: { contact: ['Contact is not at this vendor.'] }, line: { qty: ['Ensure this value is greater than or equal to 0.01.'] },
      non_field_errors: ['Provide exactly one of po_id or po.'] } });
    const { findByRole, getByRole, findByText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    expect(await findByText('Contact is not at this vendor.')).toBeInTheDocument();
    expect(await findByText(/greater than or equal to 0.01/)).toBeInTheDocument();
    expect(await findByText('Provide exactly one of po_id or po.')).toBeInTheDocument();
  });
});

describe('OrderModal — item source', () => {
  it('with no history opens in search mode, prefills qty from the host, and posts to the inventory endpoint', async () => {
    mockApi({ history: { vendors: [], earmarks: [], open_drafts: [] } });
    api.get.mockImplementation((url) => {
      if (url === '/api/inventory/7/') return Promise.resolve(ITEM);
      if (url.startsWith('/api/inventory/7/vendor-history/')) return Promise.resolve({ vendors: [], earmarks: [], open_drafts: [] });
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [{ id: 3, name: 'Materials' }] });
      if (url.startsWith('/api/businesses/?search=')) return Promise.resolve({ results: [{ business_id: 5, business_name: 'Acme Steel', default_contact: 9 }] });
      if (url === '/api/businesses/5/') return Promise.resolve({ business_id: 5, business_name: 'Acme Steel', default_contact: 9 });
      if (url.startsWith('/api/contacts/?business=5')) return Promise.resolve({ results: [{ contact_id: 9, first_name: 'Sam', last_name: 'Acme' }] });
      return Promise.resolve([]);
    });
    const { findByRole, findByPlaceholderText, getByLabelText, getByRole } = render(OrderModal, {
      props: { source: 'item', item: { inventory_item_id: 7, code: 'BB34P' }, prefillQty: '3', onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    const search = await findByPlaceholderText('Search business…');
    expect(getByLabelText(/^Qty/).value).toBe('3');
    expect(getByLabelText(/^Price/).value).toBe('60.00');       // item default
    expect(getByRole('button', { name: 'Create PO' })).toBeDisabled();   // no vendor yet
    await fireEvent.input(search, { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /Acme Steel/ }));
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('9'));
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/inventory/7/order/', {
      po: { business: 5, contact: 9, requested_date: null },
      line: { qty: '3', units: 'sheet', price: '60.00', description: '3/4 Baltic Birch', vendor_sku: '', accounting_category: 3 },
    }));
  });

  it('a blank qty is reported under the field before any request', async () => {
    mockApi({ history: { ...HISTORY, open_drafts: [] } });   // no draft choice pending, so Submit is enabled
    const { findByRole, getByLabelText, getByRole, findByText } = render(OrderModal, {
      props: { source: 'item', item: { inventory_item_id: 7, code: 'BB34P' }, prefillQty: '0', onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await findByRole('combobox', { name: /Vendor/ });
    await fireEvent.input(getByLabelText(/^Qty/), { target: { value: '' } });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    expect(await findByText('Enter a quantity greater than 0.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('Cancel calls onCancel and nothing is posted', async () => {
    const onCancel = vi.fn();
    const { findByRole, getByRole } = render(OrderModal, {
      props: { source: 'item', item: { inventory_item_id: 7, code: 'BB34P' }, prefillQty: '1', onDone: vi.fn(), onCancel },
    });
    await findByRole('dialog', { name: 'Order' });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });
});
