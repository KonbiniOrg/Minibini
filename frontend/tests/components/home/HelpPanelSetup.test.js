import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { setupStatus } from '@/stores/setupStatus.js';
import HelpPanel from '@/components/home/HelpPanel.svelte';

beforeEach(() => setupStatus.set({ areas: null, last_pull_at: null }));

describe('HelpPanel setup checklist', () => {
  it('leads with unmet gates', () => {
    setupStatus.set({ areas: {
      email: { available: false, message: 'Add your email service configuration on Settings → Email.' },
      jobs: { available: true, message: '' },
    }, last_pull_at: null });
    const { getByText } = render(HelpPanel);
    expect(getByText('Finish setting up')).toBeInTheDocument();
    expect(getByText(/email service configuration/)).toBeInTheDocument();
  });

  it('shows no checklist when every gate passes (or unloaded)', () => {
    const { queryByText, rerender } = render(HelpPanel);
    expect(queryByText('Finish setting up')).toBeNull();
    setupStatus.set({ areas: {
      email: { available: true, message: '' },
    }, last_pull_at: null });
    expect(queryByText('Finish setting up')).toBeNull();
  });
});
