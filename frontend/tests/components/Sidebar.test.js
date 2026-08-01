import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn(), get: vi.fn() } }));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { viewMode } from '@/stores/viewMode.js';
import { setupStatus } from '@/stores/setupStatus.js';
import Sidebar from '@/components/Sidebar.svelte';

beforeEach(() => {
  push.mockReset();
  api.post.mockReset();
  api.post.mockResolvedValue(undefined);
  user.set({ username: 'rachel', permissions: [] });
  viewMode.set('lite');
  setupStatus.set({ areas: null, last_pull_at: null });
});

describe('Sidebar', () => {
  it('hides admin links without permissions', () => {
    const { getByText, queryByText } = render(Sidebar);
    expect(getByText('Home')).toBeInTheDocument();
    expect(queryByText('Expenses')).toBeNull();
    expect(queryByText('Users')).toBeNull();
    expect(queryByText('Settings')).toBeNull();
  });

  it('shows Users and Settings with can_manage_config', () => {
    user.set({ username: 'rachel', permissions: ['can_manage_config'] });
    const { getByText } = render(Sidebar);
    expect(getByText('Users')).toBeInTheDocument();
    expect(getByText('Settings')).toBeInTheDocument();
  });

  it('shows Expenses with can_manage_financials', () => {
    user.set({ username: 'rachel', permissions: ['can_manage_financials'] });
    const { getByText } = render(Sidebar);
    expect(getByText('Expenses')).toBeInTheDocument();
  });

  it('shows Catalog to any authenticated user (read access, no atom needed)', () => {
    user.set({ username: 'w', permissions: [] });
    expect(render(Sidebar).getByText('Catalog')).toBeInTheDocument();
  });

  it('submits a search', async () => {
    const { getByLabelText } = render(Sidebar);
    const input = getByLabelText('Search');
    await fireEvent.input(input, { target: { value: 'bolt' } });
    await fireEvent.submit(input.closest('form'));
    expect(push).toHaveBeenCalledWith('/search?q=bolt');
  });

  it('toggles the view mode', async () => {
    const { getByRole } = render(Sidebar);
    await fireEvent.click(getByRole('button', { name: 'FULL' }));
    expect(get(viewMode)).toBe('full');
  });

  it('logs out', async () => {
    const { getByRole } = render(Sidebar);
    await fireEvent.click(getByRole('button', { name: 'Logout' }));
    expect(api.post).toHaveBeenCalledWith('/api/auth/logout/');
  });

  // Leaving deliberately must not look like being timed out: LoginPage
  // restores whatever page the hash still names, so logout has to clear it.
  it('sends the browser home on logout', async () => {
    const { getByRole } = render(Sidebar);
    await fireEvent.click(getByRole('button', { name: 'Logout' }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith('/'));
  });

  it('shows the Financials section with Invoices and Expenses for financials users', () => {
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    const { getByText, queryByText } = render(Sidebar);
    expect(getByText('Financials')).toBeInTheDocument();
    expect(getByText('Invoices')).toBeInTheDocument();
    expect(getByText('Expenses')).toBeInTheDocument();
  });

  it('hides Financials section for users without the atom', () => {
    user.set({ username: 'worker', permissions: [] });
    const { queryByText } = render(Sidebar);
    expect(queryByText('Financials')).not.toBeInTheDocument();
    expect(queryByText('Invoices')).not.toBeInTheDocument();
  });
});


describe('Sidebar setup gating', () => {
  it('renders all entries as links when gates are unloaded', () => {
    const { getByText } = render(Sidebar);
    expect(getByText('Email').tagName).toBe('A');
    expect(getByText('Catalog').tagName).toBe('A');
  });

  it('greys an unavailable area and shows its callout on hover', async () => {
    setupStatus.set({ areas: {
      email: { available: false, message: 'Add your email service configuration on Settings → Email.' },
      jobs: { available: true, message: '' },
      catalog: { available: true, message: '' },
      purchasing: { available: true, message: '' },
      invoices: { available: true, message: '' },
      estimates: { available: true, message: '' },
    }, last_pull_at: null });
    const { getByText, queryByText, findByRole } = render(Sidebar);
    const email = getByText('Email');
    expect(email.tagName).toBe('SPAN');
    expect(getByText('Jobs').tagName).toBe('A');
    expect(queryByText(/email service configuration/)).toBeNull();
    await fireEvent.mouseEnter(email);
    const callout = await findByRole('tooltip');
    expect(callout.textContent).toContain('Settings → Email');
    await fireEvent.mouseLeave(email);
    expect(queryByText(/email service configuration/)).toBeNull();
  });
});
