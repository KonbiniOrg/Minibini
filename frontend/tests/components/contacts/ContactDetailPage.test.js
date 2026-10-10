import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen, within } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({
  push: vi.fn(),
  link: () => {},
}));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import { user } from '@/stores/auth.js';
import { viewMode } from '@/stores/viewMode.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import ContactDetailPage from '@/routes/contacts/ContactDetailPage.svelte';

beforeEach(() => {
  clearMessage();
  push.mockReset();
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.patch.mockReset();
  viewMode.set('full');
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
  api.get.mockImplementation((url) => {
    if (url === '/api/contacts/1/') {
      return Promise.resolve({ contact_id: 1, name: 'Jane', email: 'j@x.com', tags: [], jobs: [] });
    }
    if (url.includes('/history/')) return Promise.resolve([]);
    if (url.includes('/financials/')) return Promise.resolve({});
    return Promise.resolve({ results: [] });
  });
});

describe('ContactDetailPage global overlay messages', () => {
  it('shows the global success overlay and navigates after a confirmed delete', async () => {
    // Two-phase delete: first call returns the impact, second executes.
    api.delete
      .mockResolvedValueOnce({ confirm_required: true, impact: { jobs: 2 } })
      .mockResolvedValueOnce({ message: 'Contact deleted.' });

    render(ContactDetailPage, { props: { params: { id: '1' } } });

    await fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    await fireEvent.click(await screen.findByRole('button', { name: 'Yes, delete' }));

    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'success', text: 'Contact deleted.' });
    });
    expect(push).toHaveBeenCalledWith('/contacts');
    // No page-local overlay markup remains.
    expect(document.querySelector('.success-overlay')).toBeNull();
  });

  it('raises the global error overlay when delete fails', async () => {
    api.delete.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Cannot delete this contact.' },
    }));

    render(ContactDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));

    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'Cannot delete this contact.' });
    });
    expect(document.querySelector('.error-overlay')).toBeNull();
  });
});

describe('ContactDetailPage edit modal', () => {
  it('edit save reloads the contact and stays', async () => {
    api.patch.mockResolvedValue({ contact_id: 1, name: 'Renamed', email: 'j@x.com', tags: [], jobs: [] });
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit contact' });
    // Submit the native form (the mock contact has no first/last name, so a
    // click would be stopped by `required` validation before reaching us).
    await fireEvent.submit(within(dialog).getByRole('button', { name: 'Save' }).closest('form'));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/contacts/1/', expect.any(Object)));
    await vi.waitFor(() => {
      expect(api.get.mock.calls.filter((c) => c[0] === '/api/contacts/1/').length).toBeGreaterThanOrEqual(2);
    });
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
