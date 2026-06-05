import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/stores/currentBlep.js', async () => {
  const { writable } = await import('svelte/store');
  return { currentBlep: writable(null) };
});
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));

import { currentBlep } from '@/stores/currentBlep.js';
import { api } from '@/lib/api.js';
import CurrentBlepBand from '@/components/CurrentBlepBand.svelte';

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({});
  currentBlep.set(null);
});

describe('CurrentBlepBand', () => {
  it('renders nothing when no blep is running', () => {
    const { queryByText } = render(CurrentBlepBand);
    expect(queryByText(/Working on/)).toBeNull();
  });

  it('offers Stop once past the minimum', async () => {
    currentBlep.set({ task: { id: 5, name: 'Cut' }, start_time: new Date(Date.now() - 120000).toISOString(), blep_minimum_minutes: 1 });
    const { getByText, getByRole } = render(CurrentBlepBand);
    expect(getByText(/Cut/)).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Stop' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/stop-work/', {});
  });

  it('offers Cancel while under the minimum', async () => {
    currentBlep.set({ task: { id: 5, name: 'Cut' }, start_time: new Date().toISOString(), blep_minimum_minutes: 1 });
    const { getByRole } = render(CurrentBlepBand);
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/cancel-work/', {});
  });
});
