import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import ContactFormModal from '@/components/contacts/ContactFormModal.svelte';

beforeEach(() => {
  push.mockReset();
  api.get.mockReset(); api.post.mockReset(); api.patch.mockReset();
  api.get.mockResolvedValue({ results: [] }); // BusinessPicker search
});

async function fillRequired(getByLabelText) {
  await fireEvent.input(getByLabelText(/First Name/), { target: { value: 'Casey' } });
  await fireEvent.input(getByLabelText(/Last Name/), { target: { value: 'Contact' } });
  await fireEvent.input(getByLabelText(/^Email/), { target: { value: 'c@example.com' } });
}

const DUP = { status: 409, data: { code: 'duplicate_email', existing_contact: { contact_id: 3, name: 'Casey Contact', email: 'c@example.com' } } };

describe('ContactFormModal — create', () => {
  it('posts and navigates to the new contact', async () => {
    api.post.mockResolvedValue({ contact_id: 9 });
    const onClose = vi.fn();
    const { getByLabelText, getByRole } = render(ContactFormModal, { props: { open: true, onClose } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/contacts/', expect.objectContaining({ email: 'c@example.com' })));
    expect(onClose).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/contacts/9');
  });

  it('seeds the business from defaultBusinessId', async () => {
    api.post.mockResolvedValue({ contact_id: 9 });
    const { getByLabelText, getByRole } = render(ContactFormModal, { props: { open: true, defaultBusinessId: 4 } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/contacts/', expect.objectContaining({ business_id: 4 })));
  });

  it('shows the duplicate notice as a sub-state and keeps the typed values behind it', async () => {
    api.post.mockRejectedValue(DUP);
    const { getByLabelText, getByRole, findByText, queryByRole } = render(ContactFormModal, { props: { open: true } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    expect(await findByText('This contact may already exist')).toBeInTheDocument();
    // Still ONE dialog — the notice is a sub-state, not a second modal.
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(1);
    expect(queryByRole('button', { name: 'Create' })).toBeNull(); // form hidden
    await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
    expect(getByLabelText(/First Name/).value).toBe('Casey');
  });

  it('Escape backs out of the duplicate notice instead of closing', async () => {
    api.post.mockRejectedValue(DUP);
    const onClose = vi.fn();
    const { getByLabelText, getByRole, findByText } = render(ContactFormModal, { props: { open: true, onClose } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await findByText('This contact may already exist');
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    expect(getByLabelText(/First Name/).value).toBe('Casey');
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('View Existing Contact closes and navigates', async () => {
    api.post.mockRejectedValue(DUP);
    const onClose = vi.fn();
    const { getByLabelText, getByRole, findByRole } = render(ContactFormModal, { props: { open: true, onClose } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await fireEvent.click(await findByRole('button', { name: 'View Existing Contact' }));
    expect(onClose).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/contacts/3');
  });

  it('renders field errors under inputs', async () => {
    api.post.mockRejectedValue({ status: 400, data: { email: ['Enter a valid email address.'] } });
    const { getByLabelText, getByRole, findByText } = render(ContactFormModal, { props: { open: true } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    expect(await findByText('Enter a valid email address.')).toBeInTheDocument();
  });

  it('reopening shows a clean form', async () => {
    api.post.mockRejectedValue({ status: 400, data: { email: ['Bad.'] } });
    const { getByLabelText, getByRole, findByText, rerender, queryByText } = render(ContactFormModal, { props: { open: true } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await findByText('Bad.');
    await rerender({ open: false });
    await rerender({ open: true });
    expect(queryByText('Bad.')).toBeNull();
    expect(getByLabelText(/First Name/).value).toBe('');
  });
});

describe('ContactFormModal — edit', () => {
  const CONTACT = { contact_id: 5, first_name: 'Old', last_name: 'Name', email: 'o@example.com', business: null };

  it('prefills, patches and calls onSaved without navigating', async () => {
    api.patch.mockResolvedValue({ ...CONTACT, first_name: 'New' });
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(ContactFormModal, { props: { open: true, contact: CONTACT, onSaved } });
    expect(getByLabelText(/First Name/).value).toBe('Old');
    await fireEvent.input(getByLabelText(/First Name/), { target: { value: 'New' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/contacts/5/', expect.objectContaining({ first_name: 'New' })));
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ first_name: 'New' }));
    expect(push).not.toHaveBeenCalled();
  });
});
