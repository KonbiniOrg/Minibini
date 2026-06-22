import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import PurchaseOrderForm from '@/components/purchaseorders/PurchaseOrderForm.svelte';

const BUSINESSES = [{ business_id: 2, business_name: 'Acme', default_contact: 5 }];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('/api/contacts/')) return Promise.resolve({ results: [{ contact_id: 5, first_name: 'Bob', last_name: 'X' }] });
    if (url.includes('/api/businesses/')) return Promise.resolve({ results: BUSINESSES });
    return Promise.resolve({ results: [] });
  });
});

describe('PurchaseOrderForm', () => {
  it('renders the BusinessPicker for vendor selection', () => {
    const { getByPlaceholderText } = render(PurchaseOrderForm, {
      props: { businesses: BUSINESSES, onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    // BusinessPicker renders an input with placeholder "Search business…"
    expect(getByPlaceholderText('Search business…')).toBeInTheDocument();
  });

  it('fetches contacts and auto-selects the default when a business is picked, then submits coerced values', async () => {
    const onSubmit = vi.fn();
    const { getByPlaceholderText, getByRole, findByRole } = render(PurchaseOrderForm, {
      props: { businesses: BUSINESSES, onSubmit, onCancel: vi.fn() },
    });

    // Simulate searching and picking a business via the BusinessPicker
    const pickerInput = getByPlaceholderText('Search business…');
    await fireEvent.input(pickerInput, { target: { value: 'Ac' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/businesses/?search=Ac&page_size=25');

    // Pick the result
    const acmeBtn = await findByRole('button', { name: /Acme/ });
    await fireEvent.mouseDown(acmeBtn);

    // contacts fetched for the picked business; auto-selected default appears as an option
    await findByRole('option', { name: 'Bob X' });
    expect(api.get).toHaveBeenCalledWith('/api/contacts/?business=2&page_size=100');

    await fireEvent.click(getByRole('button', { name: 'Create' }));
    expect(onSubmit).toHaveBeenCalledWith({ business: 2, contact: 5, requested_date: null });
  });

  it('shows a Save button in edit mode', () => {
    const { getByRole } = render(PurchaseOrderForm, {
      props: { po: { business: 2, contact: 5 }, businesses: BUSINESSES, onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    expect(getByRole('button', { name: 'Save' })).toBeInTheDocument();
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(PurchaseOrderForm, {
      props: { businesses: BUSINESSES, onSubmit: vi.fn(), onCancel },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});
