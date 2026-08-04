import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, findByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
import { api } from '@/lib/api.js';
import RatePromptDialog from '@/components/purchaseorders/RatePromptDialog.svelte';

function prompts() {
  return [
    { task_id: 10, task_name: 'Outsourced work', current_rate: '100.00', suggested_rate: '132.00' },
  ];
}

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
});

describe('RatePromptDialog', () => {
  it('shows current and suggested rate formatted as money', () => {
    const { getByText } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    expect(getByText('$100.00')).toBeInTheDocument();
    expect(getByText('$132.00')).toBeInTheDocument();
  });

  it('accept fetches the task, then PATCHes its rate via the job-scoped task endpoint', async () => {
    api.get.mockResolvedValue({ task_id: 10, job: { id: 5, job_number: 'JOB-5' } });
    api.patch.mockResolvedValue({});
    const { getByRole, findByText: find } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: 'Accept' }));

    await find('Updated.');
    expect(api.get).toHaveBeenCalledWith('/api/tasks/10/');
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/tasks/10/', { rate: '132.00' });
  });

  it('decline dismisses the row without calling the api', async () => {
    const { getByRole, findByText: find } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: 'Decline' }));
    await find('Declined.');
    expect(api.get).not.toHaveBeenCalled();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('shows a per-row error on PATCH failure without crashing other rows', async () => {
    api.get.mockResolvedValue({ task_id: 10, job: { id: 5 } });
    api.patch.mockRejectedValue(Object.assign(new Error('Forbidden'), {
      status: 403, data: { detail: 'You do not have permission to perform this action.' },
    }));
    const { getByRole, findByText: find } = render(RatePromptDialog, { props: { prompts: prompts(), onClose: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: 'Accept' }));
    expect(await find('You do not have permission to perform this action.')).toBeInTheDocument();
  });

  it('calls onClose from the Close button', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(RatePromptDialog, { props: { prompts: prompts(), onClose } });
    await fireEvent.click(getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });
});
