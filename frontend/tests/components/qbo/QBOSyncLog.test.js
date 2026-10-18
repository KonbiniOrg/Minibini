// Settings → QBO Log: read-only, paginated QBOSyncLog table.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn() },
  errorMessage: vi.fn((err, fallback) => fallback || 'Something went wrong.'),
}));

import { api } from '@/lib/api.js';
import QBOSyncLog from '@/components/qbo/QBOSyncLog.svelte';
import { viewMode } from '@/stores/viewMode.js';

const row = (id, over = {}) => ({
  id,
  entity_type: 'expense',
  entity_id: 40 + id,
  qbo_entity_type: 'Purchase',
  qbo_entity_id: `Q${id}`,
  action: 'create',
  status: 'success',
  error_message: '',
  synced_at: '2026-10-16T14:05:00Z',
  triggered_by_name: 'Ada Lovelace',
  ...over,
});

const paged = (results, count = results.length) => ({ count, next: null, previous: null, results });

beforeEach(() => {
  api.get.mockReset();
  viewMode.set('full');
});

describe('QBOSyncLog', () => {
  it('fetches the sync log and renders one row per entry', async () => {
    api.get.mockResolvedValue(paged([
      row(1),
      row(2, { status: 'failed', qbo_entity_id: '', error_message: 'QBO timeout', entity_type: 'invoice', qbo_entity_type: 'Invoice' }),
    ]));
    const { findByText, getByText, getAllByText, container } = render(QBOSyncLog);

    expect(await findByText('expense #41')).toBeInTheDocument();
    expect(getByText('invoice #42')).toBeInTheDocument();
    expect(getByText('QBO timeout')).toBeInTheDocument();
    expect(getByText('Purchase Q1')).toBeInTheDocument();
    expect(getAllByText('Ada Lovelace')).toHaveLength(2);
    expect(api.get.mock.calls[0][0]).toMatch(/^\/api\/qbo\/sync-log\/\?/);
    expect(container.querySelector('tr.failed')).not.toBeNull();
  });

  it('lite density hides the QBO and By columns, keeps When/Entity/Status/Error', async () => {
    viewMode.set('lite');
    api.get.mockResolvedValue(paged([row(1, { status: 'failed', error_message: 'boom' })]));
    const { findByText, queryByText, getByText } = render(QBOSyncLog);
    await findByText('expense #41');
    expect(queryByText('Purchase Q1')).toBeNull();
    expect(queryByText('Ada Lovelace')).toBeNull();
    expect(getByText('boom')).toBeInTheDocument();
  });

  it('shows a dash for cron-triggered rows with no user', async () => {
    api.get.mockResolvedValue(paged([row(1, { triggered_by_name: null })]));
    const { findByText } = render(QBOSyncLog);
    await findByText('expense #41');
    const byCell = document.querySelector('td[data-col="by"]');
    expect(byCell.textContent.trim()).toBe('—');
  });

  it('shows the empty state when there are no entries', async () => {
    api.get.mockResolvedValue(paged([]));
    const { findByText } = render(QBOSyncLog);
    expect(await findByText('No QBO sync activity yet.')).toBeInTheDocument();
  });

  it('shows the load error text when the fetch fails', async () => {
    api.get.mockRejectedValue(new Error('nope'));
    const { findByRole } = render(QBOSyncLog);
    const alert = await findByRole('alert');
    expect(alert.textContent).toContain('Could not load the QBO sync log.');
  });

  it('status filter refetches with status= and resets to page 1', async () => {
    api.get.mockResolvedValue(paged([row(1)]));
    const { findByText, getByLabelText } = render(QBOSyncLog);
    await findByText('expense #41');
    api.get.mockClear();

    await fireEvent.change(getByLabelText('Status'), { target: { value: 'failed' } });

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    const url = api.get.mock.calls[0][0];
    expect(url).toContain('status=failed');
    expect(url).toContain('page=1');
  });

  it('entity filter refetches with entity_type=', async () => {
    api.get.mockResolvedValue(paged([row(1)]));
    const { findByText, getByLabelText } = render(QBOSyncLog);
    await findByText('expense #41');
    api.get.mockClear();

    await fireEvent.change(getByLabelText('Entity'), { target: { value: 'invoice' } });

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get.mock.calls[0][0]).toContain('entity_type=invoice');
  });

  it('pages: Next refetches page 2', async () => {
    const results = Array.from({ length: 25 }, (_, i) => row(i + 1));
    api.get.mockResolvedValue({ count: 30, next: '/api/qbo/sync-log/?page=2', previous: null, results });
    const { findByText, getByRole } = render(QBOSyncLog);
    await findByText('expense #41');
    api.get.mockClear();

    await fireEvent.click(getByRole('button', { name: 'Next' }));

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get.mock.calls[0][0]).toContain('page=2');
  });
});
