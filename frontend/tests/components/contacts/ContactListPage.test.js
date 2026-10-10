import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));
vi.mock('@/components/qboimport/ContactsImportPanel.svelte', async () =>
  ({ default: (await import('./_Noop.svelte')).default }));
vi.mock('@/components/qboimport/QboPullButton.svelte', async () =>
  ({ default: (await import('./_Noop.svelte')).default }));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import { user } from '@/stores/auth.js';
import ContactListPage from '@/routes/contacts/ContactListPage.svelte';

function mockLists({ contacts, businesses }) {
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/tags/')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/contacts/')) return Promise.resolve({ count: contacts.length, results: contacts });
    if (url.startsWith('/api/businesses/')) return Promise.resolve({ count: businesses.length, results: businesses });
    return Promise.resolve({});
  });
}

const jane = {
  contact_id: 1, name: 'Jane Doe', email: 'jane@example.com', work_number: '555-0100',
  business: { business_id: 1, business_name: 'Acme Corp' },
  tags: [{ tag_id: 3, name: 'vip' }],
};
const acme = { business_id: 1, business_name: 'Acme Corp', business_phone: '555-0200', tags: [] };

function headers(container) {
  return Array.from(container.querySelectorAll('thead th')).map((th) => th.textContent.trim());
}

beforeEach(() => {
  api.get.mockReset();
  api.delete.mockReset();
  viewMode.set('lite');
  user.set({ id: 1, permissions: [] });
  mockLists({ contacts: [jane], businesses: [acme] });
});

describe('ContactListPage — DataTable pilot', () => {
  it('renders a contact and a business that share an id as two rows', async () => {
    const { container } = render(ContactListPage);
    await waitFor(() => expect(container.querySelectorAll('tbody tr')).toHaveLength(2));
    const names = Array.from(container.querySelectorAll('td[data-col="name"]')).map((td) => td.textContent.trim());
    expect(names).toEqual(['Acme Corp', 'Jane Doe']); // sorted by name
  });

  it('renders the same six columns in lite and full (no lite-content decisions yet), stamped with data-col', async () => {
    const { container } = render(ContactListPage);
    await waitFor(() => expect(container.querySelector('table')).toBeTruthy());
    const all = ['Name', 'Type', 'Business', 'Email', 'Phone', 'Tags'];
    expect(headers(container)).toEqual(all);
    const tagCells = Array.from(container.querySelectorAll('td[data-col="tags"]')).map((td) => td.textContent);
    expect(tagCells.join(' ')).toContain('vip');
    const callsBefore = api.get.mock.calls.length;
    viewMode.set('full');
    await tick();
    expect(headers(container)).toEqual(all);
    expect(api.get.mock.calls.length).toBe(callsBefore); // density toggle never refetches
  });

  it('links the name to the detail route and the business column to the business', async () => {
    const { getByRole, getAllByRole } = render(ContactListPage);
    await waitFor(() => getByRole('link', { name: 'Jane Doe' }));
    expect(getByRole('link', { name: 'Jane Doe' })).toHaveAttribute('href', '#/contacts/1');
    // "Acme Corp" appears as the business row's name link and as Jane's business link.
    const acmeLinks = getAllByRole('link', { name: 'Acme Corp' });
    expect(acmeLinks.map((a) => a.getAttribute('href'))).toEqual(['#/businesses/1', '#/businesses/1']);
  });

  it('shows the dash when a row has no business', async () => {
    mockLists({ contacts: [{ ...jane, business: null }], businesses: [] });
    const { container } = render(ContactListPage);
    await waitFor(() => expect(container.querySelector('table')).toBeTruthy());
    expect(container.querySelector('td[data-col="business"]').textContent.trim()).toBe('—');
  });

  it('shows "No results found." when both lists are empty', async () => {
    mockLists({ contacts: [], businesses: [] });
    const { findByText } = render(ContactListPage);
    expect(await findByText('No results found.')).toBeInTheDocument();
  });

  it('shows the load error as an alert when a list fetch rejects', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/tags/')) return Promise.resolve({ results: [] });
      return Promise.reject(new Error('boom'));
    });
    const { findByRole } = render(ContactListPage);
    expect(await findByRole('alert')).toHaveTextContent('boom');
  });
});
