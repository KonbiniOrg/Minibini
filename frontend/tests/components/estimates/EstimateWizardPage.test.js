import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import EstimateWizardPage from '@/routes/estimates/EstimateWizardPage.svelte';

beforeEach(() => {
  clearMessage();
});

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
  it('shows "Tasks & Materials" as the page title', async () => {
    mockApi(makeEstimate());

    render(EstimateWizardPage, { props: { params: { id: '11' } } });

    expect(await screen.findByText(/Tasks & Materials/i)).toBeInTheDocument();
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

  it('shows the "back to Estimate" link', async () => {
    mockApi(makeEstimate());

    render(EstimateWizardPage, { props: { params: { id: '11' } } });

    const back = await screen.findByText(/back to estimate/i);
    expect(back.getAttribute('href')).toBe('/estimates/11');
  });
});

describe('EstimateWizardPage add-atoms error handling', () => {
  const AVAILABLE_ATOM = {
    type: 'task', id: 3, description: 'Cut parts', state: 'available',
    qty: '1', rate: '10.00', units: 'none', amount: '10.00',
  };

  function mockApiWithAtom(estimate) {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === `/api/estimates/${estimate.estimate_id}/`) return Promise.resolve({ ...estimate });
      if (url.includes('/line-items/')) return Promise.resolve({ results: [] });
      if (url.includes('/source-pool/')) return Promise.resolve({ atoms: [{ ...AVAILABLE_ATOM }] });
      if (url.startsWith('/api/jobs/')) return Promise.resolve({ job_id: 9, job_number: 'JOB-9', name: 'Job', contact: null });
      return Promise.resolve({});
    });
  }

  async function selectAtomAndAdd() {
    render(EstimateWizardPage, { props: { params: { id: '11' } } });
    const checkbox = await screen.findByRole('checkbox');
    await fireEvent.click(checkbox);
    await fireEvent.click(screen.getByRole('button', { name: 'Add Here' }));
  }

  it('renders the 409 atoms-claimed conflict as a form message with a Reload wizard affordance', async () => {
    mockApiWithAtom(makeEstimate());
    api.post.mockReset();
    api.post.mockRejectedValue(Object.assign(new Error('Conflict'), {
      status: 409,
      data: { detail: 'Some atoms were claimed by another estimate.', code: 'atoms_already_claimed' },
    }));

    await selectAtomAndAdd();

    const msg = await screen.findByRole('alert');
    expect(msg.textContent).toContain('Some atoms were claimed by another estimate.');
    // Conflict is a form-venue message, not the global overlay.
    expect(get(overlayMessage)).toBeNull();

    // The next-step affordance reloads the wizard (source pool included).
    const poolCallsBefore = api.get.mock.calls.filter(([u]) => u.includes('/source-pool/')).length;
    await fireEvent.click(screen.getByRole('button', { name: 'Reload wizard' }));
    expect(api.get.mock.calls.filter(([u]) => u.includes('/source-pool/')).length)
      .toBe(poolCallsBefore + 1);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('raises the global overlay for non-409 add failures', async () => {
    mockApiWithAtom(makeEstimate());
    api.post.mockReset();
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Estimate is not editable.' },
    }));

    await selectAtomAndAdd();

    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'Estimate is not editable.' });
    });
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
