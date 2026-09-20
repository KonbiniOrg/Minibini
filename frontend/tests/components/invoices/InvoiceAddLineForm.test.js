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

  it('service choice prefills description from template_name and omits it untouched', async () => {
    const choice = { type: 'service',
                     serviceItem: { template_id: 11, template_name: 'CNC' } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42,
               categories: cats, onSaved: vi.fn() } });
    expect(getByLabelText(/description/i)).toHaveValue('CNC');
    await fireEvent.click(getByRole('button', { name: /add/i }));
    const [, payload] = api.post.mock.calls.at(-1);
    expect('description' in payload).toBe(false);
  });

  it('service choice sends an edited description as an override', async () => {
    const choice = { type: 'service',
                     serviceItem: { template_id: 11, template_name: 'CNC' } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42,
               categories: cats, onSaved: vi.fn() } });
    await fireEvent.input(getByLabelText(/description/i), { target: { value: 'CNC (edited)' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/42/line-items-from-service/',
      expect.objectContaining({ description: 'CNC (edited)' }));
  });

  it('inventory choice prefills description from the PLI and omits it untouched', async () => {
    const choice = { type: 'inventory',
                     inventoryItem: { inventory_item_id: 9, description: 'Widget' } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42,
               categories: cats, onSaved: vi.fn() } });
    expect(getByLabelText(/description/i)).toHaveValue('Widget');
    await fireEvent.click(getByRole('button', { name: /add/i }));
    const [, payload] = api.post.mock.calls.at(-1);
    expect('description' in payload).toBe(false);
  });

  it('inventory choice sends an edited description as an override', async () => {
    const choice = { type: 'inventory',
                     inventoryItem: { inventory_item_id: 9, description: 'Widget' } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42,
               categories: cats, onSaved: vi.fn() } });
    await fireEvent.input(getByLabelText(/description/i), { target: { value: 'Widget, blue' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/42/line-items/',
      expect.objectContaining({ description: 'Widget, blue' }));
  });
});
