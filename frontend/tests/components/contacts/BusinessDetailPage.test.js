import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import { user } from '@/stores/auth.js';
import { viewMode } from '@/stores/viewMode.js';
import BusinessDetailPage from '@/routes/contacts/BusinessDetailPage.svelte';

beforeEach(() => {
  push.mockReset();
  api.get.mockReset(); api.patch.mockReset();
  viewMode.set('full');
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
  api.get.mockImplementation((url) => {
    if (url === '/api/businesses/1/') {
      return Promise.resolve({ business_id: 1, business_name: 'Acme', default_contact: { contact_id: 9, name: 'Boss' }, tags: [], jobs: [], contacts: [] });
    }
    if (url.includes('/history/')) return Promise.resolve([]);
    if (url.includes('/financials/')) return Promise.resolve({});
    if (url.startsWith('/api/payment-terms/')) return Promise.resolve([]);
    return Promise.resolve({ results: [] });
  });
});

describe('BusinessDetailPage edit modal', () => {
  it('edit save reloads the business and stays', async () => {
    api.patch.mockResolvedValue({ business_id: 1, business_name: 'Acme 2', default_contact: { contact_id: 9, name: 'Boss' }, tags: [], jobs: [], contacts: [] });
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
