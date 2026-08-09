import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('@/stores/jobWorkspace.js', () => ({ rememberMode: vi.fn() }));

import { api } from '@/lib/api.js';
import { rememberMode } from '@/stores/jobWorkspace.js';
import EstimateWizardRedirect from '@/routes/estimates/EstimateWizardRedirect.svelte';

beforeEach(() => {
  api.get.mockReset();
  rememberMode.mockReset();
  window.location.hash = '#/estimates/11/wizard';
});

describe('EstimateWizardRedirect shim', () => {
  it('fetches the estimate, remembers edit mode, then replaces the hash with the job-scoped URL', async () => {
    api.get.mockResolvedValue({ estimate_id: 11, job: 9 });

    render(EstimateWizardRedirect, { props: { params: { id: '11' } } });

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/estimates/11/'));
    await waitFor(() => expect(rememberMode).toHaveBeenCalledWith(9, 'est:11', 'edit'));
    await waitFor(() => expect(window.location.hash).toBe('#/jobs/9/estimate/11'));
  });

  it('redirects to the job list if the estimate fetch fails', async () => {
    api.get.mockRejectedValue(new Error('not found'));

    render(EstimateWizardRedirect, { props: { params: { id: '11' } } });

    await waitFor(() => expect(window.location.hash).toBe('#/jobs'));
    expect(rememberMode).not.toHaveBeenCalled();
  });
});
