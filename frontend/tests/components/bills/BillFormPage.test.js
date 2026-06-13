import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, findByText, findByRole, queryByRole } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), querystring: { subscribe: vi.fn((fn) => { fn(''); return () => {}; }) }, link: () => {} }));

import { api } from '@/lib/api.js';
import BillFormPage from '@/routes/bills/BillFormPage.svelte';

const BUSINESSES = [
  { business_id: 1, business_name: 'Acme Supply', default_contact: null },
  { business_id: 2, business_name: 'Widget Co', default_contact: null },
];

const DRAFT_BILL = {
  bill_id: 5,
  vendor_invoice_number: 'V-5',
  vendor_name: 'Acme Supply',
  business: 1,
  contact: null,
  status: 'draft',
  due_date: '2026-07-15T00:00:00Z',
  received_date: null,
  paid_date: null,
  balance: '0.00',
  line_items: [],
};

const RECEIVED_BILL = {
  ...DRAFT_BILL,
  bill_id: 6,
  vendor_invoice_number: 'V-6',
  status: 'received',
};

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('/api/businesses/')) return Promise.resolve({ results: BUSINESSES });
    if (url.includes('/api/contacts/')) return Promise.resolve({ results: [] });
    return Promise.resolve(DRAFT_BILL);
  });
});

describe('BillFormPage', () => {
  it('new mode renders the form with a Save button and loads businesses into the vendor select', async () => {
    const { container } = render(BillFormPage, { props: { params: {} } });

    // Wait for businesses to load and Save button to appear
    const saveBtn = await findByRole(container, 'button', { name: 'Save' });
    expect(saveBtn).toBeInTheDocument();

    // Vendor select should contain the businesses from the API
    expect(await findByText(container, 'Acme Supply')).toBeInTheDocument();
    expect(await findByText(container, 'Widget Co')).toBeInTheDocument();

    // API called for businesses
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/businesses/'));
    // Should not call the bills endpoint in new mode
    const callUrls = api.get.mock.calls.map(c => c[0]);
    expect(callUrls.every(url => !url.includes('/api/bills/'))).toBe(true);
  });

  it('edit mode on a non-draft bill shows the read-only notice instead of the form', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/businesses/')) return Promise.resolve({ results: BUSINESSES });
      if (url.includes('/api/bills/')) return Promise.resolve(RECEIVED_BILL);
      return Promise.resolve({ results: [] });
    });

    const { container } = render(BillFormPage, { props: { params: { id: '6' } } });

    // Wait for load to finish — the notice text should appear
    await findByText(container, /can no longer be edited/i);

    // The form's Save button must NOT be present
    expect(queryByRole(container, 'button', { name: 'Save' })).toBeNull();

    // Status is shown in the notice
    expect(await findByText(container, /received/)).toBeInTheDocument();
  });

  it('edit mode on a draft bill shows the prefilled form', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/businesses/')) return Promise.resolve({ results: BUSINESSES });
      if (url.includes('/api/bills/')) return Promise.resolve(DRAFT_BILL);
      if (url.includes('/api/contacts/')) return Promise.resolve({ results: [] });
      return Promise.resolve({ results: [] });
    });

    const { container } = render(BillFormPage, { props: { params: { id: '5' } } });

    const saveBtn = await findByRole(container, 'button', { name: 'Save' });
    expect(saveBtn).toBeInTheDocument();

    // Vendor invoice number should be prefilled
    const invInput = container.querySelector('#vendor_invoice_number');
    expect(invInput).not.toBeNull();
    expect(invInput.value).toBe('V-5');
  });
});
