import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn(), get: vi.fn() } }));
// jsdom refuses to redefine window.location.reload (unforgeable) and can't
// perform the navigation anyway, so the reload goes through lib/navigation.js.
vi.mock('@/lib/navigation.js', () => ({ reloadPage: vi.fn() }));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import { reloadPage as reload } from '@/lib/navigation.js';
import { user } from '@/stores/auth.js';
import LoginPage from '@/routes/LoginPage.svelte';

beforeEach(() => {
  push.mockReset();
  api.post.mockReset();
  reload.mockReset();
  user.set(null);
  window.location.hash = '';
});

async function submitLogin() {
  const { getByLabelText, getByRole } = render(LoginPage);
  await fireEvent.input(getByLabelText('Username'), { target: { value: 'rachel' } });
  await fireEvent.input(getByLabelText('Password'), { target: { value: 'pw' } });
  await fireEvent.click(getByRole('button', { name: 'Log In' }));
}

describe('LoginPage landing', () => {
  it('sends a first-ever login to the Help tab', async () => {
    api.post.mockResolvedValue({ id: 1, username: 'rachel', first_login: true });
    window.location.hash = '#/jobs/42';
    await submitLogin();
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith('/help'));
    expect(reload).not.toHaveBeenCalled();
  });

  it('sends a login from the root hash to Home', async () => {
    api.post.mockResolvedValue({ id: 1, username: 'rachel', first_login: false });
    window.location.hash = '#/';
    await submitLogin();
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith('/'));
    expect(reload).not.toHaveBeenCalled();
  });

  it('sends a login with no hash at all to Home', async () => {
    api.post.mockResolvedValue({ id: 1, username: 'rachel', first_login: false });
    await submitLogin();
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith('/'));
    expect(reload).not.toHaveBeenCalled();
  });

  it('reloads in place when the hash still names a page (expiry / deep link)', async () => {
    api.post.mockResolvedValue({ id: 1, username: 'rachel', first_login: false });
    window.location.hash = '#/jobs/42';
    await submitLogin();
    await vi.waitFor(() => expect(reload).toHaveBeenCalled());
    expect(push).not.toHaveBeenCalled();
    expect(window.location.hash).toBe('#/jobs/42');
  });

  it('treats a root hash carrying a querystring as Home, not a page to restore', async () => {
    api.post.mockResolvedValue({ id: 1, username: 'rachel', first_login: false });
    window.location.hash = '#/?tab=shifts';
    await submitLogin();
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith('/'));
    expect(reload).not.toHaveBeenCalled();
  });

  it('shows the expiry notice when given one', () => {
    const { getByText } = render(LoginPage, { props: { notice: 'Your session expired.' } });
    expect(getByText('Your session expired.')).toBeInTheDocument();
  });
});
