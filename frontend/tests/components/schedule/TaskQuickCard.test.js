import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import TaskQuickCard from '@/components/schedule/TaskQuickCard.svelte';

function bar(overrides) {
  return { task_id: 5, name: 'Cut', status: 'pending', accent_color: '#888', est_minutes: 30, elapsed_minutes: 0, is_running: false, job_id: 3, ...overrides };
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ task_id: 5, name: 'Cut', status: 'pending' });
  api.post.mockResolvedValue({});
  user.set({ id: 1, permissions: [] });
});

describe('TaskQuickCard', () => {
  it('renders the bar and closes', async () => {
    const onClose = vi.fn();
    const { getByText, getByRole } = render(TaskQuickCard, { props: { bar: bar(), onClose } });
    expect(getByText('Cut')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows the job number and name from the bar itself', async () => {
    const { getByText, getByRole } = render(TaskQuickCard, {
      props: { bar: bar({ job_number: 'JOB-2025-0007', job_name: 'Widget Run' }), onClose: vi.fn() },
    });
    const link = getByRole('link', { name: 'JOB-2025-0007' });
    expect(link).toHaveAttribute('href', '#/jobs/3');
    expect(getByText(/Widget Run/)).toBeInTheDocument();
  });

  it('starts work on behalf of the lane worker', async () => {
    user.set({ id: 1, permissions: ['can_manage_time'] });
    const onClose = vi.fn();
    const { findByRole } = render(TaskQuickCard, {
      props: { bar: bar(), laneWorkerId: 2, assigneeName: 'Sam', onClose },
    });
    await fireEvent.click(await findByRole('button', { name: /Start for/ }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/', { on_behalf_of: 2 });
    expect(onClose).toHaveBeenCalled();
  });
});
