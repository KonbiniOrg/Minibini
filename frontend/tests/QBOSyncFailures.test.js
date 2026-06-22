// frontend/tests/QBOSyncFailures.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, findByText, queryByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: vi.fn((err, fallback) => fallback || 'Something went wrong.'),
}));

import { api } from '@/lib/api.js';
import QBOSyncFailures from '@/components/qbo/QBOSyncFailures.svelte';

const FAILURES = [
  {
    entity_type: 'expense',
    id: 1,
    label: 'Expense #1: Paint supplies',
    amount: '100.00',
    qbo_pending_op: 'create',
    qbo_sync_error: 'QBO timeout',
    retry_url: '/api/expenses/1/retry-sync/',
  },
  {
    entity_type: 'bill_payment',
    id: 7,
    label: 'Payment on bill INV-001',
    amount: '200.00',
    qbo_pending_op: 'create',
    qbo_sync_error: 'Auth failed',
    retry_url: '/api/bills/3/payments/7/retry-sync/',
  },
];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ failures: FAILURES });
  api.post.mockResolvedValue({ retried: 2, still_failing: 0 });
});

describe('QBOSyncFailures', () => {
  it('renders both failure labels', async () => {
    const { container } = render(QBOSyncFailures);
    expect(await findByText(container, 'Expense #1: Paint supplies')).toBeInTheDocument();
    expect(await findByText(container, 'Payment on bill INV-001')).toBeInTheDocument();
  });

  it('renders a Retry all button', async () => {
    const { container } = render(QBOSyncFailures);
    expect(await findByText(container, 'Retry all')).toBeInTheDocument();
  });

  it('clicking Retry all calls the retry-all endpoint and reloads the list', async () => {
    const { container } = render(QBOSyncFailures);
    const btn = await findByText(container, 'Retry all');

    // Reset mock count so we can assert the reload call
    api.get.mockClear();
    api.post.mockResolvedValue({ retried: 2, still_failing: 0 });

    await fireEvent.click(btn);
    // Wait for async handlers to settle
    await new Promise(r => setTimeout(r, 0));

    expect(api.post).toHaveBeenCalledWith('/api/qbo/sync-failures/retry-all/');
    expect(api.get).toHaveBeenCalledWith('/api/qbo/sync-failures/');
  });

  it('shows empty state when no failures', async () => {
    api.get.mockResolvedValue({ failures: [] });
    const { container } = render(QBOSyncFailures);
    expect(await findByText(container, 'No QBO sync failures.')).toBeInTheDocument();
  });

  it('each row has a per-row Retry button', async () => {
    const { container } = render(QBOSyncFailures);
    await findByText(container, 'Expense #1: Paint supplies'); // wait for load
    const retryBtns = container.querySelectorAll('button.retry-row');
    expect(retryBtns.length).toBe(2);
  });
});
