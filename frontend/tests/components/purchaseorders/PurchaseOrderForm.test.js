import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import PurchaseOrderForm from '@/components/purchaseorders/PurchaseOrderForm.svelte';

const BUSINESSES = [{ business_id: 2, business_name: 'Acme', default_contact: 5 }];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ results: [{ contact_id: 5, first_name: 'Bob', last_name: 'X' }] });
});

describe('PurchaseOrderForm', () => {
  it('fetches contacts and auto-selects the default on business change, then submits coerced values', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole, findByRole } = render(PurchaseOrderForm, {
      props: { businesses: BUSINESSES, onSubmit, onCancel: vi.fn() },
    });

    await fireEvent.change(getByLabelText(/Vendor/), { target: { value: '2' } });
    // contacts fetched for the business; auto-selected default appears as an option
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
