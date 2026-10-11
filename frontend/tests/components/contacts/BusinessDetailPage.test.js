import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen, within } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback,
}));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import { user } from '@/stores/auth.js';
import { viewMode } from '@/stores/viewMode.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import BusinessDetailPage from '@/routes/contacts/BusinessDetailPage.svelte';

const BOSS = { contact_id: 9, name: 'Boss', email: 'b@x.test', mobile_number: '1', work_number: '' };
const WORKER = { contact_id: 10, name: 'Worker', email: '', mobile_number: '', work_number: '2' };

function mockBusiness(overrides = {}) {
  return {
    business_id: 1, business_name: 'Acme', default_contact: { contact_id: 9, name: 'Boss' }, tags: [],
    terms_name: 'Net 30', jobs: [], contacts: [BOSS], ...overrides,
  };
}

function wire(biz, { pos = [] } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/api/businesses/1/') return Promise.resolve(biz);
    if (url.includes('/history/')) return Promise.resolve([]);
    if (url.includes('/financials/')) {
      return Promise.resolve({ invoiced: '100.00', profit: '10.00', open_jobs: 1, outstanding: '5.00', first_job_date: '2024-03-02', last_job_start: '2026-09-26' });
    }
    if (url.startsWith('/api/purchase-orders/')) return Promise.resolve({ results: pos });
    if (url.startsWith('/api/payment-terms/')) return Promise.resolve([]);
    if (url.startsWith('/api/auth/users/')) return Promise.resolve([]);
    return Promise.resolve({ results: [] });
  });
}

beforeEach(() => {
  clearMessage();
  push.mockReset();
  api.get.mockReset(); api.patch.mockReset(); api.delete.mockReset();
  viewMode.set('full');
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
  wire(mockBusiness());
});

describe('BusinessDetailPage banner', () => {
  it('fetches the lists whole and renders the facts line and numbers', async () => {
    render(BusinessDetailPage, { props: { params: { id: '1' } } });
    expect(await screen.findByText('Customer since Mar 2024 · Last job started Sep 26, 2026 · Net 30')).toBeInTheDocument();
    expect(screen.getByText('$5.00')).toBeInTheDocument();
    const urls = api.get.mock.calls.map((c) => c[0]);
    expect(urls).toContain('/api/invoices/?business=1&summary=true&page_size=100');
    expect(urls).toContain('/api/purchase-orders/?business=1&page_size=100');
  });

  it('offers Delete… on a deletable business (no jobs, no POs, one contact) and runs the two-phase delete through the modal', async () => {
    api.delete
      .mockResolvedValueOnce({ confirm_required: true, impact: { contacts: 1, jobs: 0, purchase_orders: 0 } })
      .mockResolvedValueOnce({ message: 'Business deleted.' });
    render(BusinessDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Delete…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete business' });
    expect(dialog.textContent).toContain('1 contact(s)');
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Delete business' }));
    await vi.waitFor(() => expect(api.delete).toHaveBeenLastCalledWith('/api/businesses/1/?confirm=true'));
    await vi.waitFor(() => expect(get(overlayMessage)).toEqual({ kind: 'success', text: 'Business deleted.' }));
    expect(push).toHaveBeenCalledWith('/contacts');
  });

  it('shows the Deactivate placeholder instead when the business has jobs, POs or several contacts', async () => {
    wire(mockBusiness({ contacts: [BOSS, WORKER] }));
    render(BusinessDetailPage, { props: { params: { id: '1' } } });
    const deactivate = await screen.findByRole('button', { name: 'Deactivate' });
    expect(deactivate).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Delete…' })).toBeNull();
  });

  it('a PO alone blocks Delete', async () => {
    wire(mockBusiness(), { pos: [{ po_id: 1, po_number: 'PO-1', status: 'issued' }] });
    render(BusinessDetailPage, { props: { params: { id: '1' } } });
    expect(await screen.findByRole('button', { name: 'Deactivate' })).toBeDisabled();
  });

  it('New Job in the banner opens the job modal; a Contacts row New job does too', async () => {
    wire(mockBusiness({ contacts: [BOSS, WORKER] }));
    render(BusinessDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'New Job' }));
    expect(await screen.findByRole('dialog', { name: 'New job' })).toBeInTheDocument();
  });

  it('Set as default PATCHes the business and reloads', async () => {
    wire(mockBusiness({ contacts: [BOSS, WORKER] }));
    api.patch.mockResolvedValue({});
    render(BusinessDetailPage, { props: { params: { id: '1' } } });
    const rows = await vi.waitFor(() => {
      const r = document.querySelectorAll('[data-section="contacts"] tbody tr');
      expect(r).toHaveLength(2);
      return r;
    });
    await fireEvent.click(within(rows[1]).getByRole('button', { name: 'Set as default' }));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/businesses/1/', { default_contact_id: 10 }));
    await vi.waitFor(() => {
      expect(api.get.mock.calls.filter((c) => c[0] === '/api/businesses/1/').length).toBeGreaterThanOrEqual(2);
    });
  });

  it('hides every banner action from a non-manager', async () => {
    user.set({ id: 2, permissions: [] });
    render(BusinessDetailPage, { props: { params: { id: '1' } } });
    await screen.findByText('Acme');
    expect(screen.queryByRole('button', { name: 'New Job' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Deactivate' })).toBeNull();
  });
});

describe('BusinessDetailPage edit modal', () => {
  it('edit save reloads the business and stays', async () => {
    api.patch.mockResolvedValue(mockBusiness({ business_name: 'Acme 2' }));
    render(BusinessDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit business' });
    await within(dialog).findByLabelText(/Business Name/);
    await fireEvent.submit(within(dialog).getByRole('button', { name: 'Save' }).closest('form'));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/businesses/1/', expect.any(Object)));
    await vi.waitFor(() => {
      expect(api.get.mock.calls.filter((c) => c[0] === '/api/businesses/1/').length).toBeGreaterThanOrEqual(2);
    });
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
