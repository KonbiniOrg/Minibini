import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import JobCreateModal from '@/components/jobs/JobCreateModal.svelte';

beforeEach(() => {
  push.mockReset();
  api.get.mockReset(); api.post.mockReset();
});

function mockUsers(users) {
  api.get.mockImplementation((url) => url.startsWith('/api/auth/users/')
    ? Promise.resolve(users) : Promise.resolve({ results: [] }));
}

describe('JobCreateModal', () => {
  it('loads users on open and lists them in the PM select', async () => {
    mockUsers([{ id: 2, name: 'Bob Brown' }]);
    const { findByRole } = render(JobCreateModal, { props: { open: true } });
    expect(await findByRole('option', { name: 'Bob Brown' })).toBeInTheDocument();
  });

  it('seeds the contact from defaultContactId and posts it, then navigates', async () => {
    mockUsers([]);
    api.post.mockResolvedValue({ job_id: 77 });
    const onClose = vi.fn();
    const { findByRole } = render(JobCreateModal, { props: { open: true, defaultContactId: 5, onClose } });
    await fireEvent.click(await findByRole('button', { name: 'Create' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/jobs/', expect.objectContaining({ contact: 5 })));
    expect(onClose).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/jobs/77');
  });

  it('renders field errors and stays open', async () => {
    mockUsers([]);
    api.post.mockRejectedValue({ status: 400, data: { contact: ['This field is required.'] } });
    const onClose = vi.fn();
    const { findByRole, findByText } = render(JobCreateModal, { props: { open: true, onClose } });
    await fireEvent.click(await findByRole('button', { name: 'Create' }));
    expect(await findByText('This field is required.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
