import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));

import { api } from '@/lib/api.js';
import StartWorkConflictModal from '@/components/tasks/StartWorkConflictModal.svelte';

const conflict = { worker: { name: 'Sam' }, started_at: '2026-03-01T09:00:00' };

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({});
});

describe('StartWorkConflictModal', () => {
  it('renders nothing without a conflict', () => {
    const { queryByText } = render(StartWorkConflictModal, { props: { conflict: null, taskId: 5 } });
    expect(queryByText(/already working/i)).toBeNull();
  });

  it('joins the existing session (carrying prior_qty_handled — the prior-session prompt already ran on the first post)', async () => {
    const onResolved = vi.fn();
    const { getByRole } = render(StartWorkConflictModal, { props: { conflict, taskId: 5, onResolved } });
    await fireEvent.click(getByRole('button', { name: /Join/ }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/', { action: 'join', prior_qty_handled: true });
    expect(onResolved).toHaveBeenCalled();
  });

  it('takes over on behalf of a worker', async () => {
    const { getByRole } = render(StartWorkConflictModal, { props: { conflict, taskId: 5, onBehalfOf: 2 } });
    await fireEvent.click(getByRole('button', { name: /Take over/ }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/', { action: 'takeover', on_behalf_of: 2, prior_qty_handled: true });
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(StartWorkConflictModal, { props: { conflict, taskId: 5, onCancel } });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});
