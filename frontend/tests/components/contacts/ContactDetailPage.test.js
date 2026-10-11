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

function mockContact(overrides = {}) {
  return { contact_id: 1, name: 'Jane', email: 'j@x.com', tags: [], jobs: [], business: null, ...overrides };
}
const BIZ_SUMMARY = { business_id: 7, business_name: 'Acme', default_contact: { contact_id: 1, name: 'Jane' } };
const BIZ_DETAIL = {
  business_id: 7, business_name: 'Acme', terms_name: null, business_phone: '', tax_exemption_number: '',
  contacts: [{ contact_id: 1, name: 'Jane' }, { contact_id: 2, name: 'Marcus' }], jobs: [{ job_id: 5, contact: 2 }],
};

function wire(contact, business = BIZ_DETAIL) {
  api.get.mockImplementation((url) => {
    if (url === '/api/contacts/1/') return Promise.resolve(contact);
    if (url === '/api/businesses/7/') return Promise.resolve(business);
    if (url.includes('/history/')) return Promise.resolve([]);
    if (url.includes('/financials/')) return Promise.resolve({ invoiced: '0.00', profit: '0.00', open_jobs: 0, outstanding: '0.00', first_job_date: null, last_job_start: null });
    if (url.startsWith('/api/auth/users/')) return Promise.resolve([]);
    return Promise.resolve({ results: [] });
  });
}

beforeEach(() => {
  clearMessage();
  push.mockReset();
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.patch.mockReset();
  viewMode.set('full');
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
  wire(mockContact());
});

describe('ContactDetailPage delete / deactivate', () => {
  it('a job-less individual gets Delete…; the modal runs the two-phase delete, shows the global success overlay and navigates', async () => {
    api.delete
      .mockResolvedValueOnce({ confirm_required: true, impact: { jobs: 0 } })
      .mockResolvedValueOnce({ message: 'Contact deleted.' });

    render(ContactDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Delete…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete contact' });
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Delete contact' }));

    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'success', text: 'Contact deleted.' });
    });
    expect(api.delete).toHaveBeenLastCalledWith('/api/contacts/1/?confirm=true');
    expect(push).toHaveBeenCalledWith('/contacts');
    expect(document.querySelector('.success-overlay')).toBeNull();
  });

  it('raises the global error overlay when delete fails', async () => {
    api.delete.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Cannot delete this contact.' },
    }));
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Delete…' }));
    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'Cannot delete this contact.' });
    });
    expect(document.querySelector('.error-overlay')).toBeNull();
  });

  it('a contact with jobs gets the disabled Deactivate placeholder', async () => {
    wire(mockContact({ jobs: [{ job_id: 1, job_number: 'JOB-1', name: 'x', status: 'draft', contact: 1, contact_name: 'Jane', created_date: '2026-01-01T00:00:00Z' }] }));
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    expect(await screen.findByRole('button', { name: 'Deactivate' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Delete…' })).toBeNull();
  });

  it('the only contact of a business cannot be deleted; with a sibling it can', async () => {
    wire(mockContact({ business: BIZ_SUMMARY }), { ...BIZ_DETAIL, contacts: [{ contact_id: 1, name: 'Jane' }], jobs: [] });
    const first = render(ContactDetailPage, { props: { params: { id: '1' } } });
    expect(await screen.findByRole('button', { name: 'Deactivate' })).toBeDisabled();
    first.unmount();

    wire(mockContact({ business: BIZ_SUMMARY }));
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    expect(await screen.findByRole('button', { name: 'Delete…' })).toBeInTheDocument();
  });
});

describe('ContactDetailPage business context', () => {
  it('fetches the business detail, shows the default-contact chip and the sibling list', async () => {
    wire(mockContact({ business: BIZ_SUMMARY }));
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    expect(await screen.findByText('default contact')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Marcus' })).toHaveAttribute('href', '#/contacts/2');
    expect(screen.getByText('1 job')).toBeInTheDocument();
    expect(api.get.mock.calls.map((c) => c[0])).toContain('/api/businesses/7/');
    // status=all: the endpoint defaults to the 'open' preset, which would drop paid invoices.
    expect(api.get.mock.calls.map((c) => c[0])).toContain('/api/invoices/?contact=1&status=all&summary=true&page_size=100');
  });

  it('New Job in the banner opens the job modal', async () => {
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'New Job' }));
    expect(await screen.findByRole('dialog', { name: 'New job' })).toBeInTheDocument();
  });
});

describe('ContactDetailPage edit modal', () => {
  it('edit save reloads the contact and stays', async () => {
    api.patch.mockResolvedValue(mockContact({ name: 'Renamed' }));
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit contact' });
    await fireEvent.submit(within(dialog).getByRole('button', { name: 'Save' }).closest('form'));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/contacts/1/', expect.any(Object)));
    await vi.waitFor(() => {
      expect(api.get.mock.calls.filter((c) => c[0] === '/api/contacts/1/').length).toBeGreaterThanOrEqual(2);
    });
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
