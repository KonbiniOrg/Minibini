import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
vi.mock('@/stores/messages.js', () => ({ showSuccess: vi.fn(), showError: vi.fn() }));

import { api } from '@/lib/api.js';
import { showSuccess } from '@/stores/messages.js';
import ChangePasswordModal from '@/components/users/ChangePasswordModal.svelte';

beforeEach(() => { api.post.mockReset(); showSuccess.mockReset(); });

describe('ChangePasswordModal', () => {
  it('renders a dialog with a hidden username field and the three password fields', async () => {
    const { findByRole, container } = render(ChangePasswordModal, { props: { open: true, username: 'rachel' } });
    const dialog = await findByRole('dialog', { name: 'Change password' });
    const u = container.querySelector('input[autocomplete="username"]');
    expect(u.value).toBe('rachel');
    expect(u).toHaveAttribute('name', 'username');
    expect(within(dialog).getByLabelText('Current password')).toHaveAttribute('autocomplete', 'current-password');
    expect(within(dialog).getByLabelText('Current password')).toHaveAttribute('name', 'current_password');
    expect(within(dialog).getByLabelText('New password')).toHaveAttribute('name', 'new_password');
    expect(within(dialog).getByLabelText('New password')).toHaveAttribute('autocomplete', 'new-password');
  });

  it('posts and closes on success with a success overlay', async () => {
    api.post.mockResolvedValue({});
    const onClose = vi.fn();
    const { findByRole, getByLabelText, getByRole } = render(ChangePasswordModal, { props: { open: true, username: 'rachel', onClose } });
    await findByRole('dialog');
    await fireEvent.input(getByLabelText('Current password'), { target: { value: 'old' } });
    await fireEvent.input(getByLabelText('New password'), { target: { value: 'newpass1' } });
    await fireEvent.input(getByLabelText('Confirm new password'), { target: { value: 'newpass1' } });
    await fireEvent.click(getByRole('button', { name: 'Change password' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/auth/me/password/', {
      current_password: 'old', new_password: 'newpass1', new_password_confirm: 'newpass1',
    }));
    expect(showSuccess).toHaveBeenCalledWith('Password changed.');
    expect(onClose).toHaveBeenCalled();
  });

  it('shows field errors and stays open', async () => {
    api.post.mockRejectedValue({ status: 400, data: { current_password: ['Wrong password.'] } });
    const onClose = vi.fn();
    const { findByRole, getByLabelText, getByRole, findByText } = render(ChangePasswordModal, { props: { open: true, username: 'rachel', onClose } });
    await findByRole('dialog');
    await fireEvent.input(getByLabelText('Current password'), { target: { value: 'bad' } });
    await fireEvent.input(getByLabelText('New password'), { target: { value: 'newpass1' } });
    await fireEvent.input(getByLabelText('Confirm new password'), { target: { value: 'newpass1' } });
    await fireEvent.click(getByRole('button', { name: 'Change password' }));
    expect(await findByText('Wrong password.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
