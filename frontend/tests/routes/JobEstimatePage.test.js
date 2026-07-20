import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { getJobWs, rememberSection } from '@/stores/jobWorkspace.js';
import JobEstimatePage from '@/routes/jobs/JobEstimatePage.svelte';

const job = { job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress', contact: null, can_manage: true };

function est(id, version, status = 'draft') {
  return {
    estimate_id: id, estimate_number: `EST-${id}`, job: 3, version, status,
    can_manage: true, is_amended: false, line_items: [],
    created_date: '2026-01-01T00:00:00Z', sent_date: null, expiration_date: null, closed_date: null,
  };
}

function mockApi({ estimates = [], byId = {} } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('/emails/')) return Promise.resolve({ results: [] });
    if (url.includes('/deliverables/')) return Promise.resolve([]);
    if (url.startsWith('/api/estimates/?job=')) return Promise.resolve({ results: estimates });
    if (url.startsWith('/api/change-orders/?job=')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/settings/')) return Promise.resolve({});
    const m = url.match(/^\/api\/estimates\/(\d+)\/$/);
    if (m && byId[m[1]]) return Promise.resolve(byId[m[1]]);
    if (url === '/api/jobs/3/') return Promise.resolve(job);
    return Promise.resolve(null);
  });
}

beforeEach(() => {
  localStorage.clear();
  window.location.hash = '';
});

describe('JobEstimatePage document resolution', () => {
  it('uses the URL docId when present', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });

    const { findByText } = render(JobEstimatePage, {
      props: { params: { jobId: '3', docId: '7' } },
    });

    expect(await findByText('Estimate: EST-7')).toBeInTheDocument();
  });

  it('falls back to the remembered doc on a bare route', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });
    rememberSection('3', 'estimate', '7');

    const { findByText } = render(JobEstimatePage, {
      props: { params: { jobId: '3' } },
    });

    expect(await findByText('Estimate: EST-7')).toBeInTheDocument();
  });

  it('falls back to the latest version when nothing is remembered', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });

    const { findByText } = render(JobEstimatePage, {
      props: { params: { jobId: '3' } },
    });

    expect(await findByText('Estimate: EST-8')).toBeInTheDocument();
  });

  it('ignores a remembered doc id that is no longer in the job\'s estimate list', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });
    rememberSection('3', 'estimate', '999');

    const { findByText } = render(JobEstimatePage, {
      props: { params: { jobId: '3' } },
    });

    expect(await findByText('Estimate: EST-8')).toBeInTheDocument();
  });

  it('normalizes the URL to the resolved doc via replaceState on a bare route', async () => {
    const e1 = est(7, 1);
    mockApi({ estimates: [e1], byId: { 7: e1 } });

    render(JobEstimatePage, { props: { params: { jobId: '3' } } });

    await waitFor(() => expect(window.location.hash).toBe('#/jobs/3/estimate/7'));
    expect(getJobWs('3').sections.estimate).toBe('7');
  });

  it('shows the gated empty state when the job has no estimates', async () => {
    // The fixture job is in_progress — past the quoting phase — so the
    // empty state explains instead of offering Start Estimate (which the
    // backend would refuse; the draft-job button case is covered in the
    // EstimatePanel tests).
    mockApi({ estimates: [] });
    const { findByText, queryByRole } = render(JobEstimatePage, { props: { params: { jobId: '3' } } });
    expect(await findByText(/past the estimating phase/i)).toBeInTheDocument();
    expect(queryByRole('button', { name: /start estimate/i })).toBeNull();
  });
});

describe('JobEstimatePage doc-subnav navigation (no job-context refetch)', () => {
  it('does not refetch the job or estimate list when only docId changes', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });

    const { findByText, rerender } = render(JobEstimatePage, {
      props: { params: { jobId: 3, docId: '7' } },
    });
    expect(await findByText('Estimate: EST-7')).toBeInTheDocument();

    // Fresh params object, same jobId — this is what svelte-spa-router hands
    // the still-mounted component on every doc-subnav navigation.
    await rerender({ params: { jobId: 3, docId: '8' } });
    expect(await findByText('Estimate: EST-8')).toBeInTheDocument();

    const jobFetches = api.get.mock.calls.filter(([url]) => url === '/api/jobs/3/');
    const estimateListFetches = api.get.mock.calls.filter(([url]) => url.startsWith('/api/estimates/?job='));

    expect(jobFetches).toHaveLength(1);
    expect(estimateListFetches).toHaveLength(2);
  });
});
