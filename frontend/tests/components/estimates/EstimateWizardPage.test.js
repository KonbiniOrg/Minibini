import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { api } from '@/lib/api.js';
import EstimateWizardPage from '@/routes/estimates/EstimateWizardPage.svelte';

function makeEstimate(overrides = {}) {
  return {
    estimate_id: 11,
    estimate_number: 'EST-11',
    job: 9,
    status: 'draft',
    can_manage: true,
    ...overrides,
  };
}

function mockApi(estimate) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === `/api/estimates/${estimate.estimate_id}/`) return Promise.resolve({ ...estimate });
    if (url.includes('/line-items/')) return Promise.resolve({ results: [] });
    if (url.includes('/source-pool/')) return Promise.resolve({ atoms: [] });
    if (url.startsWith('/api/jobs/')) return Promise.resolve({ job_id: 9, job_number: 'JOB-9', name: 'Job', contact: null });
    if (url.startsWith('/api/contacts/')) return Promise.resolve({});
    return Promise.resolve({});
  });
}

describe('EstimateWizardPage vocabulary labels', () => {
  it('shows "Customize Client View" as the page title', async () => {
    mockApi(makeEstimate());

    render(EstimateWizardPage, { props: { params: { id: '11' } } });

    expect(await screen.findByText(/Customize Client View/i)).toBeInTheDocument();
    // Old label absent
    expect(screen.queryByText(/^Worksheet:/)).not.toBeInTheDocument();
  });

  it('labels the source pool section "plan atoms" (not "worksheet atoms")', async () => {
    mockApi(makeEstimate());

    render(EstimateWizardPage, { props: { params: { id: '11' } } });

    expect(await screen.findByText(/plan atoms/i)).toBeInTheDocument();
    expect(screen.queryByText(/worksheet atoms/i)).not.toBeInTheDocument();
  });

  it('labels the back link "back to Client View"', async () => {
    mockApi(makeEstimate());

    render(EstimateWizardPage, { props: { params: { id: '11' } } });

    expect(await screen.findByText(/back to client view/i)).toBeInTheDocument();
    expect(screen.queryByText(/back to estimate/i)).not.toBeInTheDocument();
  });
});
