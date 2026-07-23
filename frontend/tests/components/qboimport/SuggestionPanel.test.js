import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e) => e?.message || 'error',
}));
vi.mock('@/stores/setupStatus.js', () => ({
  refreshSetupStatus: vi.fn(),
  setupStatus: { subscribe: (fn) => { fn({ areas: null, last_pull_at: null }); return () => {}; } },
}));

import { api } from '@/lib/api.js';
import SuggestionPanel from '@/components/qboimport/SuggestionPanel.svelte';

const table = createRawSnippet((rows) => ({
  render: () => `<div data-testid="rows">${rows().length} rows</div>`,
}));

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

function props(overrides = {}) {
  return { area: 'catalog', title: 'From QuickBooks', table,
           commit: vi.fn().mockResolvedValue({}), ...overrides };
}

describe('SuggestionPanel', () => {
  it('renders nothing when dismissed', async () => {
    api.get.mockResolvedValue({ dismissed: true, fetched_at: null, rows: [] });
    const { queryByText, container } = render(SuggestionPanel, { props: props() });
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('.qbo-panel')).toBeNull();
  });

  it('renders nothing when the diff is empty', async () => {
    api.get.mockResolvedValue({ dismissed: false, fetched_at: 'x', rows: [] });
    const { container } = render(SuggestionPanel, { props: props() });
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('.qbo-panel')).toBeNull();
  });

  it('renders rows with pull, dismiss and apply controls', async () => {
    api.get.mockResolvedValue({
      dismissed: false, fetched_at: '2026-07-23T20:00:00Z',
      rows: [{ qbo_id: '1', state: 'new' }, { qbo_id: '2', state: 'imported' }],
    });
    const { findByText, getByTestId } = render(SuggestionPanel, { props: props() });
    expect(await findByText('From QuickBooks')).toBeInTheDocument();
    expect(getByTestId('rows').textContent).toBe('2 rows');
    expect(await findByText('Apply selected')).toBeInTheDocument();
    expect(await findByText('Dismiss')).toBeInTheDocument();
  });

  it('dismiss posts and hides the panel', async () => {
    api.get
      .mockResolvedValueOnce({ dismissed: false, fetched_at: 'x',
                               rows: [{ qbo_id: '1', state: 'new' }] })
      .mockResolvedValueOnce({ dismissed: true, fetched_at: null, rows: [] });
    api.post.mockResolvedValue({});
    const { findByText, container } = render(SuggestionPanel, { props: props() });
    await fireEvent.click(await findByText('Dismiss'));
    await new Promise((r) => setTimeout(r, 0));
    expect(api.post).toHaveBeenCalledWith('/api/qbo/import/dismiss/', { area: 'catalog' });
    expect(container.querySelector('.qbo-panel')).toBeNull();
  });

  it('apply commits only checked, non-imported rows', async () => {
    const commit = vi.fn().mockResolvedValue({});
    api.get.mockResolvedValue({
      dismissed: false, fetched_at: 'x',
      rows: [{ qbo_id: '1', state: 'new' }, { qbo_id: '2', state: 'imported' }],
    });
    const { findByText } = render(SuggestionPanel, { props: props({ commit }) });
    await fireEvent.click(await findByText('Apply selected'));
    expect(commit).toHaveBeenCalledWith([{ qbo_id: '1', state: 'new' }]);
  });
});
