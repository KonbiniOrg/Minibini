import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));
vi.mock('@/stores/auth.js', () => ({ login: vi.fn() }));

import { push } from 'svelte-spa-router';
import { login } from '@/stores/auth.js';
import LoginPage from '@/routes/LoginPage.svelte';

beforeEach(() => {
  push.mockReset();
  login.mockReset();
});

async function submit(getByLabelText, getByRole) {
  await fireEvent.input(getByLabelText('Username'), { target: { value: 'sam' } });
  await fireEvent.input(getByLabelText('Password'), { target: { value: 'pw' } });
  await fireEvent.click(getByRole('button', { name: 'Log In' }));
}

describe('LoginPage', () => {
  it('lands a first-ever login on the Help tab', async () => {
    login.mockResolvedValue({ username: 'sam', first_login: true });
    const { getByLabelText, getByRole } = render(LoginPage);
    await submit(getByLabelText, getByRole);
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith('/help'));
  });

  it('lands a returning login on Home', async () => {
    login.mockResolvedValue({ username: 'sam', first_login: false });
    const { getByLabelText, getByRole } = render(LoginPage);
    await submit(getByLabelText, getByRole);
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith('/'));
  });

  it('shows the error and stays put on failure', async () => {
    login.mockRejectedValue(new Error('Invalid credentials.'));
    const { getByLabelText, getByRole, findByText } = render(LoginPage);
    await submit(getByLabelText, getByRole);
    expect(await findByText('Invalid credentials.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
