import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/stores/auth.js', async () => {
  const { writable } = await import('svelte/store');
  return { user: writable(null) };
});
vi.mock('@/stores/viewMode.js', async () => {
  const { writable } = await import('svelte/store');
  return { viewMode: writable('full'), toggleViewMode: vi.fn() };
});
vi.mock('@/lib/api.js', () => ({
  api: { patch: vi.fn(), post: vi.fn() },
}));

import { user } from '@/stores/auth.js';
import { api } from '@/lib/api.js';
import ProfilePanel from '@/components/home/ProfilePanel.svelte';

beforeEach(() => {
  api.patch.mockReset();
  api.post.mockReset();
  user.set({ username: 'rachel', email: 'r@example.com', first_name: 'Rachel', last_name: 'M' });
});

describe('ProfilePanel', () => {
  it('saves account info via PATCH /api/auth/me/ and updates the store', async () => {
    api.patch.mockResolvedValue({
      username: 'rachel', email: 'new@example.com', first_name: 'Rachel', last_name: 'M',
    });
    const { getByLabelText, getByRole, findByText } = render(ProfilePanel);
    await fireEvent.input(getByLabelText('Email'), { target: { value: 'new@example.com' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    await findByText('Saved.');
    expect(api.patch).toHaveBeenCalledWith('/api/auth/me/', {
      email: 'new@example.com', first_name: 'Rachel', last_name: 'M',
    });
  });

  it('shows field errors from a rejected save', async () => {
    api.patch.mockRejectedValue({ data: { email: ['Enter a valid email address.'] } });
    const { getByRole, findByText } = render(ProfilePanel);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText('Enter a valid email address.')).toBeInTheDocument();
  });

  it('changes the password and clears the form', async () => {
    // Snapshot the body at call time — the component clears the same
    // reactive object after a successful post.
    let sent = null;
    api.post.mockImplementation((url, body) => {
      sent = { url, body: { ...body } };
      return Promise.resolve({});
    });
    const { getByLabelText, getByRole, findByText } = render(ProfilePanel);
    await fireEvent.input(getByLabelText('Current password'), { target: { value: 'old' } });
    await fireEvent.input(getByLabelText('New password'), { target: { value: 'newpass1' } });
    await fireEvent.input(getByLabelText('Confirm new password'), { target: { value: 'newpass1' } });
    await fireEvent.click(getByRole('button', { name: 'Change password' }));
    await findByText('Password changed.');
    expect(sent).toEqual({
      url: '/api/auth/me/password/',
      body: { current_password: 'old', new_password: 'newpass1', new_password_confirm: 'newpass1' },
    });
    expect(getByLabelText('Current password').value).toBe('');
  });
});
