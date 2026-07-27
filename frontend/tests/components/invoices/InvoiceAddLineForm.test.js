import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
import { api } from '@/lib/api.js';
import InvoiceAddLineForm from '@/components/invoices/InvoiceAddLineForm.svelte';

const cats = [{ id: 7, code: 'SVC', name: 'Service' }];
beforeEach(() => { api.post.mockReset();
                   api.post.mockResolvedValue({ line_item_id: 1 }); });

describe('InvoiceAddLineForm', () => {
  it('service choice posts to line-items-from-service', async () => {
    const choice = { type: 'service',
                     serviceItem: { template_id: 11, template_name: 'CNC' } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42,
               categories: cats, onSaved: vi.fn() } });
    await fireEvent.input(getByLabelText(/quantity/i),
                          { target: { value: '3' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith(
      '/api/invoices/42/line-items-from-service/',
      { service_item: 11, qty: '3' });
  });

  it('freeform requires an accounting category', async () => {
    const { getByRole, findByText } = render(InvoiceAddLineForm, {
      props: { open: true, choice: { type: 'freeform', typed: 'Misc' },
               invoiceId: 42, categories: cats,
               onSaved: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    await findByText(/accounting category is required/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('inventory choice posts inventory_item + qty', async () => {
    const choice = { type: 'inventory',
                     inventoryItem: { inventory_item_id: 9 } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42,
               categories: cats, onSaved: vi.fn() } });
    await fireEvent.input(getByLabelText(/quantity/i),
                          { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/42/line-items/',
      { inventory_item: 9, qty: '2' });
  });
});
