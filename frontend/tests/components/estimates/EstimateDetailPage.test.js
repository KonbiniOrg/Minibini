import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import EstimateDetailPage from '@/routes/estimates/EstimateDetailPage.svelte';

beforeEach(() => {
  api.get.mockReset();
  window.location.hash = '#/estimates/7';
});

describe('EstimateDetailPage redirect shim', () => {
  it('fetches the estimate then replaces the hash with the job-scoped URL', async () => {
    api.get.mockResolvedValue({ estimate_id: 7, job: 9 });

    render(EstimateDetailPage, { props: { params: { id: '7' } } });

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/estimates/7/'));
    await waitFor(() => expect(window.location.hash).toBe('#/jobs/9/estimate/7'));
  });

  it('redirects to the job list if the estimate fetch fails', async () => {
    api.get.mockRejectedValue(new Error('not found'));

    render(EstimateDetailPage, { props: { params: { id: '7' } } });

    await waitFor(() => expect(window.location.hash).toBe('#/jobs'));
  });
});
