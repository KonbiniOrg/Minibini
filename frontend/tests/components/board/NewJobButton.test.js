import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, errorMessage: (e, f) => e?.message || f }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import NewJobButton from '@/components/board/NewJobButton.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]);
  user.set({ username: 'rachel', permissions: ['can_manage_jobs'] });
});

describe('NewJobButton', () => {
  it('is a button that opens the job modal', async () => {
    const { getByRole, findByRole, queryByRole } = render(NewJobButton);
    expect(queryByRole('link', { name: 'New Job' })).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'New Job' }));
    expect(await findByRole('dialog', { name: 'New job' })).toBeInTheDocument();
  });

  it('renders nothing without can_manage_jobs', () => {
    user.set({ username: 'sam', permissions: [] });
    const { queryByRole } = render(NewJobButton);
    expect(queryByRole('button', { name: 'New Job' })).toBeNull();
  });
});
