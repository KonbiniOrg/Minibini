import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor, screen } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import BusinessFormModal from '@/components/contacts/BusinessFormModal.svelte';

beforeEach(() => {
  push.mockReset();
  api.get.mockReset(); api.post.mockReset(); api.patch.mockReset();
});

function mockGet({ exists = false, business = null, terms = [] } = {}) {
  api.get.mockImplementation((url) => {
    if (url.includes('check-name')) return Promise.resolve({ exists, business });
    if (url.startsWith('/api/payment-terms/')) return Promise.resolve(terms);
    return Promise.resolve({ results: [] });
  });
}

async function fillCreate(getByLabelText) {
  await fireEvent.input(getByLabelText(/Business Name/), { target: { value: 'Acme' } });
  await fireEvent.input(getByLabelText('First Name *'), { target: { value: 'Ann' } });
  await fireEvent.input(getByLabelText('Last Name *'), { target: { value: 'Lee' } });
  await fireEvent.input(getByLabelText('Email *'), { target: { value: 'ann@acme.test' } });
  // Second editor on the form is the default contact's (the first is the business's).
  await fireEvent.click(screen.getAllByRole('button', { name: 'Add phone' })[1]);
  await fireEvent.input(getByLabelText('Phone 1 number'), { target: { value: '555' } });
}

describe('BusinessFormModal — create', () => {
  it('loads payment terms on open and offers them', async () => {
    mockGet({ terms: [{ id: 1, name: 'Net 30' }] });
    const { findByRole } = render(BusinessFormModal, { props: { open: true } });
    expect(await findByRole('option', { name: 'Net 30' })).toBeInTheDocument();
  });

  it('check-name → contact → business, then navigates', async () => {
    mockGet();
    api.post.mockImplementation((url) => url === '/api/contacts/'
      ? Promise.resolve({ contact_id: 7 }) : Promise.resolve({ business_id: 11 }));
    const onClose = vi.fn();
    const { getByLabelText, getByRole, findByLabelText } = render(BusinessFormModal, { props: { open: true, onClose } });
    await findByLabelText(/Business Name/);
    await fillCreate(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/businesses/11'));
    expect(api.post).toHaveBeenCalledWith('/api/businesses/', expect.objectContaining({ default_contact_id: 7 }));
    expect(onClose).toHaveBeenCalled();
  });

  it('check-name hit shows the business notice as a sub-state (nothing created)', async () => {
    mockGet({ exists: true, business: { business_id: 2, business_name: 'Acme' } });
    const { getByLabelText, getByRole, findByText, findByLabelText } = render(BusinessFormModal, { props: { open: true } });
    await findByLabelText(/Business Name/);
    await fillCreate(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    expect(await findByText('This business may already exist')).toBeInTheDocument();
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(1);
    expect(api.post).not.toHaveBeenCalled();
    await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
    expect(getByLabelText(/Business Name/).value).toBe('Acme');
  });

  it('duplicate contact email from the contact POST shows the contact notice', async () => {
    mockGet();
    api.post.mockRejectedValue({ status: 409, data: { code: 'duplicate_email', existing_contact: { contact_id: 3, name: 'Ann Lee', email: 'ann@acme.test' } } });
    const { getByLabelText, getByRole, findByText, findByLabelText } = render(BusinessFormModal, { props: { open: true } });
    await findByLabelText(/Business Name/);
    await fillCreate(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    expect(await findByText('This contact may already exist')).toBeInTheDocument();
  });
});

describe('BusinessFormModal — edit', () => {
  it('patches and calls onSaved, no navigation', async () => {
    mockGet();
    api.patch.mockResolvedValue({ business_id: 2, business_name: 'Acme 2' });
    const onSaved = vi.fn();
    const { getByLabelText, getByRole, findByLabelText } = render(BusinessFormModal, {
      props: { open: true, business: { business_id: 2, business_name: 'Acme', default_contact: null }, onSaved },
    });
    await findByLabelText(/Business Name/);
    await fireEvent.input(getByLabelText(/Business Name/), { target: { value: 'Acme 2' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/businesses/2/', expect.objectContaining({ business_name: 'Acme 2' })));
    expect(onSaved).toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });
});
