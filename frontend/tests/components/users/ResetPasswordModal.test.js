import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() }, errorMessage: (e, f) => e?.data?.detail || e?.message || f }));
vi.mock('@/stores/messages.js', () => ({ showSuccess: vi.fn(), showError: vi.fn() }));

import { api } from '@/lib/api.js';
import { showSuccess } from '@/stores/messages.js';
import ResetPasswordModal from '@/components/users/ResetPasswordModal.svelte';

const USER = { id: 4, username: 'sam' };

beforeEach(() => { api.post.mockReset(); showSuccess.mockReset(); });

describe('ResetPasswordModal', () => {
  it('renders a dialog with the target user\'s hidden username and two new-password fields', async () => {
    const { findByRole, container } = render(ResetPasswordModal, { props: { open: true, user: USER } });
    const dialog = await findByRole('dialog', { name: 'Reset password' });
    expect(dialog).toHaveTextContent('Reset password for sam');
    expect(container.querySelector('input[autocomplete="username"]').value).toBe('sam');
    expect(within(dialog).getByLabelText('New password')).toHaveAttribute('autocomplete', 'new-password');
    expect(within(dialog).getByLabelText('New password')).toHaveAttribute('name', 'password');
    expect(within(dialog).getByLabelText('Confirm new password')).toHaveAttribute('name', 'password_confirm');
  });

  it('posts to the admin reset route and closes on success', async () => {
    api.post.mockResolvedValue({});
    const onClose = vi.fn();
    const { findByRole, getByLabelText, getByRole } = render(ResetPasswordModal, { props: { open: true, user: USER, onClose } });
    await findByRole('dialog');
    await fireEvent.input(getByLabelText('New password'), { target: { value: 'newpass1' } });
    await fireEvent.input(getByLabelText('Confirm new password'), { target: { value: 'newpass1' } });
    await fireEvent.click(getByRole('button', { name: 'Reset password' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/users/4/reset-password/', { password: 'newpass1', password_confirm: 'newpass1' }));
    expect(showSuccess).toHaveBeenCalledWith('Password reset.');
    expect(onClose).toHaveBeenCalled();
  });

  it('shows field errors and stays open', async () => {
    api.post.mockRejectedValue({ status: 400, data: { password_confirm: ['Passwords do not match.'] } });
    const onClose = vi.fn();
    const { findByRole, getByLabelText, getByRole, findByText } = render(ResetPasswordModal, { props: { open: true, user: USER, onClose } });
    await findByRole('dialog');
    await fireEvent.input(getByLabelText('New password'), { target: { value: 'a' } });
    await fireEvent.input(getByLabelText('Confirm new password'), { target: { value: 'b' } });
    await fireEvent.click(getByRole('button', { name: 'Reset password' }));
    expect(await findByText('Passwords do not match.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('ResetPasswordModal — operation errors (review fix)', () => {
  it('renders a {detail} operation error in the modal instead of failing silently', async () => {
    api.post.mockRejectedValue({ status: 403, data: { detail: 'You do not have permission.' }, message: 'You do not have permission.' });
    const { findByRole, getByRole, findByText } = render(ResetPasswordModal, { props: { open: true, username: 'rachel', user: { id: 4, username: 'sam' } } });
    const dialog = await findByRole('dialog');
    const form = dialog.querySelector('form');
    await fireEvent.submit(form);
    expect(await findByText('You do not have permission.')).toBeInTheDocument();
    void getByRole;
  });
});
