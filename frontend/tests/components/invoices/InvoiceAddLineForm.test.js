import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
import { api } from '@/lib/api.js';
import InvoiceAddLineForm from '@/components/invoices/InvoiceAddLineForm.svelte';

const cats = [{ id: 7, code: 'SVC', name: 'Service' }];
beforeEach(() => { api.post.mockReset();
                   api.post.mockResolvedValue({ line_item_id: 1 }); });

describe('InvoiceAddLineForm', () => {
  it('deposit choice posts a deposit line with prefilled description', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice: { type: 'deposit', typed: '' },
               invoiceId: 42, jobNumber: 'JOB-2026-0042',
               categories: cats, onSaved } });
    const desc = getByLabelText(/description/i);
    expect(desc.value).toBe('Deposit on JOB-2026-0042');
    await fireEvent.input(getByLabelText(/amount/i),
                          { target: { value: '5000' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/42/line-items/', {
      deposit: true, description: 'Deposit on JOB-2026-0042',
      qty: '1', units: 'none', price: '5000',
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('deposit choice shows the field-keyed coaching error when the server rejects it', async () => {
    api.post.mockRejectedValue({
      status: 400,
      message: 'Bad request',
      data: {
        accounting_category: [
          'No default deposit accounting category is configured. Set the default_deposit_accounting_category setting in Settings.',
        ],
      },
    });
    const { getByLabelText, getByRole, findByText } = render(InvoiceAddLineForm, {
      props: { open: true, choice: { type: 'deposit', typed: '' },
               invoiceId: 42, jobNumber: 'JOB-2026-0042',
               categories: cats, onSaved: vi.fn() } });
    await fireEvent.input(getByLabelText(/amount/i),
                          { target: { value: '5000' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(await findByText(/default deposit accounting category/i)).toBeInTheDocument();
  });

  it('service choice posts to line-items-from-service', async () => {
    const choice = { type: 'service',
                     serviceItem: { template_id: 11, template_name: 'CNC' } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42, jobNumber: 'J',
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
               invoiceId: 42, jobNumber: 'J', categories: cats,
               onSaved: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    await findByText(/accounting category is required/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('inventory choice posts inventory_item + qty', async () => {
    const choice = { type: 'inventory',
                     inventoryItem: { inventory_item_id: 9 } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42, jobNumber: 'J',
               categories: cats, onSaved: vi.fn() } });
    await fireEvent.input(getByLabelText(/quantity/i),
                          { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/42/line-items/',
      { inventory_item: 9, qty: '2' });
  });
});
