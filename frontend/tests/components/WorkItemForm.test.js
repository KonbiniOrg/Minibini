import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import WorkItemForm from '@/components/WorkItemForm.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ results: [{ rate_scheme_id: 1, name: 'Hourly', algorithm: 'per_unit', rate: '25', unit_label: 'hr', modifiers: [] }] });
  api.post.mockResolvedValue({});
});

describe('WorkItemForm', () => {
  it('requires a name', async () => {
    const { findByRole, getByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    await fireEvent.click(await findByRole('button', { name: 'Save' }));
    expect(getByText('Name is required.')).toBeInTheDocument();
  });

  it('saves a manual task', async () => {
    const onSaved = vi.fn();
    const { findByLabelText, getByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, onSaved },
    });
    await fireEvent.change(await findByLabelText(/Rate scheme/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Cut' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      name: 'Cut', rate_scheme: 1, est_worker_time: null,
    }));
    expect(onSaved).toHaveBeenCalled();
  });
});
