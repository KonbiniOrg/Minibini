import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import DuplicateJobModal from '@/components/jobs/DuplicateJobModal.svelte';

const JOB = { job_id: 3, job_number: 'JOB-3', contact: 42 };

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/contacts/42/') {
      return Promise.resolve({ contact_id: 42, name: 'Pat Quinn', business: null });
    }
    return Promise.resolve({});
  });
  api.post.mockReset();
  api.post.mockResolvedValue({ job_id: 99 });
  push.mockReset();
});

describe('DuplicateJobModal', () => {
  it('prefills the selected contact from job.contact, enabling Duplicate', async () => {
    const { getByRole } = render(DuplicateJobModal, { props: { job: JOB, open: true } });
    await waitFor(() => {
      expect(getByRole('button', { name: /^Duplicate$/ })).not.toBeDisabled();
    });
  });

  it('posts contact_id and the chosen path, then navigates to the new job', async () => {
    const { getByRole, getByLabelText } = render(DuplicateJobModal, { props: { job: JOB, open: true } });
    await waitFor(() => expect(getByRole('button', { name: /^Duplicate$/ })).not.toBeDisabled());
    await fireEvent.click(getByLabelText(/Requires a new estimate/));
    await fireEvent.click(getByRole('button', { name: /^Duplicate$/ }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/jobs/3/duplicate/', {
        contact_id: 42,
        path: 'estimate',
      });
    });
    await waitFor(() => expect(push).toHaveBeenCalledWith('/jobs/99'));
  });

  it('re-enables the button after a failed duplicate', async () => {
    api.post.mockRejectedValue(new Error('fail'));
    const { getByRole } = render(DuplicateJobModal, { props: { job: JOB, open: true } });
    await waitFor(() => expect(getByRole('button', { name: /^Duplicate$/ })).not.toBeDisabled());
    await fireEvent.click(getByRole('button', { name: /^Duplicate$/ }));
    await waitFor(() => {
      expect(getByRole('button', { name: /^Duplicate$/ })).not.toBeDisabled();
    });
    expect(push).not.toHaveBeenCalled();
  });

  it('resets to the "approved" path and re-prefills when reopened for a different job', async () => {
    const { getByRole, getByLabelText, rerender } = render(DuplicateJobModal, {
      props: { job: JOB, open: true },
    });
    await waitFor(() => expect(getByRole('button', { name: /^Duplicate$/ })).not.toBeDisabled());
    await fireEvent.click(getByLabelText(/Requires a new estimate/));
    await rerender({ job: JOB, open: false });
    await rerender({ job: JOB, open: true });
    expect(getByLabelText(/Immediately approved/).checked).toBe(true);
  });
});
