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
    worksheet: 22,
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

  it('labels the source pool section "job atoms" (not "plan atoms" or "worksheet atoms")', async () => {
    mockApi(makeEstimate());

    render(EstimateWizardPage, { props: { params: { id: '11' } } });

    expect(await screen.findByText(/job atoms/i)).toBeInTheDocument();
    expect(screen.queryByText(/plan atoms/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/worksheet atoms/i)).not.toBeInTheDocument();
  });

  it('shows only the "back to Client View" link (worksheet back-link removed)', async () => {
    mockApi(makeEstimate());

    render(EstimateWizardPage, { props: { params: { id: '11' } } });

    const cv = await screen.findByText(/back to client view/i);
    expect(cv.getAttribute('href')).toBe('/estimates/11');
    expect(screen.queryByText(/back to estimate/i)).not.toBeInTheDocument();
  });
});
