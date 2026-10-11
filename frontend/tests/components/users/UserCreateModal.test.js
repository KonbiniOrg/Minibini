import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() }, errorMessage: (e, f) => e?.message || f }));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import UserCreateModal from '@/components/users/UserCreateModal.svelte';

beforeEach(() => { push.mockReset(); api.post.mockReset(); });

async function fill(getByLabelText) {
  await fireEvent.input(getByLabelText('Username *'), { target: { value: 'sam' } });
  await fireEvent.input(getByLabelText('Email *'), { target: { value: 's@x.y' } });
  await fireEvent.input(getByLabelText('First name *'), { target: { value: 'Sam' } });
  await fireEvent.input(getByLabelText('Last name *'), { target: { value: 'Lee' } });
  await fireEvent.input(getByLabelText('Password *'), { target: { value: 'pw12345678' } });
  await fireEvent.input(getByLabelText('Confirm password *'), { target: { value: 'pw12345678' } });
}

describe('UserCreateModal', () => {
  it('posts the form, closes and navigates to the new user', async () => {
    api.post.mockResolvedValue({ id: 12 });
    const onClose = vi.fn();
    const { getByLabelText, getByRole, findByRole } = render(UserCreateModal, { props: { open: true, onClose } });
    await findByRole('dialog', { name: 'New user' });
    await fill(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create user' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/users/', expect.objectContaining({ username: 'sam', password: 'pw12345678' })));
    expect(onClose).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/users/12');
  });

  it('marks the username field for password managers', async () => {
    const { findByLabelText } = render(UserCreateModal, { props: { open: true } });
    expect(await findByLabelText('Username *')).toHaveAttribute('autocomplete', 'username');
  });

  it('renders field errors and stays open', async () => {
    api.post.mockRejectedValue({ status: 400, data: { username: ['Taken.'] } });
    const onClose = vi.fn();
    const { getByLabelText, getByRole, findByText, findByRole } = render(UserCreateModal, { props: { open: true, onClose } });
    await findByRole('dialog');
    await fill(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create user' }));
    expect(await findByText('Taken.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('UserCreateModal — operation errors (review fix)', () => {
  it('renders a {detail} operation error in the modal instead of failing silently', async () => {
    api.post.mockRejectedValue({ status: 403, data: { detail: 'You do not have permission.' }, message: 'You do not have permission.' });
    const { findByRole, getByRole, findByText } = render(UserCreateModal, { props: { open: true, username: 'rachel', user: { id: 4, username: 'sam' } } });
    const dialog = await findByRole('dialog');
    const form = dialog.querySelector('form');
    await fireEvent.submit(form);
    expect(await findByText('You do not have permission.')).toBeInTheDocument();
    void getByRole;
  });
});
