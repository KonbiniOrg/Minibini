import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { viewMode } from '@/stores/viewMode.js';
import Sidebar from '@/components/Sidebar.svelte';

beforeEach(() => {
  push.mockReset();
  api.post.mockReset();
  api.post.mockResolvedValue(undefined);
  user.set({ username: 'rachel', permissions: [] });
  viewMode.set('lite');
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

  it('shows the Financials section with Invoices, Bills, and Expenses for financials users', () => {
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    const { getByText, queryByText } = render(Sidebar);
    expect(getByText('Financials')).toBeInTheDocument();
    expect(getByText('Invoices')).toBeInTheDocument();
    expect(getByText('Bills')).toBeInTheDocument();
    expect(getByText('Expenses')).toBeInTheDocument();
  });

  it('hides Financials section for users without the atom', () => {
    user.set({ username: 'worker', permissions: [] });
    const { queryByText } = render(Sidebar);
    expect(queryByText('Financials')).not.toBeInTheDocument();
    expect(queryByText('Invoices')).not.toBeInTheDocument();
    expect(queryByText('Bills')).not.toBeInTheDocument();
  });
});
