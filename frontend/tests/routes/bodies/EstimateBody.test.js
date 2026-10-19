import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));

import { api } from '@/lib/api.js';
import { getJobWs, rememberSection } from '@/stores/jobWorkspace.js';
import EstimateBody from '@/routes/jobs/bodies/EstimateBody.svelte';

// Ported from the retired JobEstimatePage tests: the body owns the estimates
// list and the docId precedence; the job itself is owned by JobWorkspace.
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
    if (url.startsWith('/api/estimates/?job=')) return Promise.resolve({ results: estimates });
    if (url.startsWith('/api/change-orders/?job=')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/settings/')) return Promise.resolve({});
    const m = url.match(/^\/api\/estimates\/(\d+)\/$/);
    if (m && byId[m[1]]) return Promise.resolve(byId[m[1]]);
    return Promise.resolve(null);
  });
}

const jobFetches = () => api.get.mock.calls.filter(([url]) => url === '/api/jobs/3/');

beforeEach(() => {
  localStorage.clear();
  window.location.hash = '';
});

describe('EstimateBody document resolution', () => {
  it('uses the URL docId when present', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });
    const { findByText } = render(EstimateBody, { props: { job, params: { jobId: '3', docId: '7' } } });
    expect(await findByText(/Estimate: EST-7-\d/)).toBeInTheDocument();
  });

  it('falls back to the remembered doc on a bare route', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });
    rememberSection('3', 'estimate', '7');
    const { findByText } = render(EstimateBody, { props: { job, params: { jobId: '3' } } });
    expect(await findByText(/Estimate: EST-7-\d/)).toBeInTheDocument();
  });

  it('falls back to the latest version when nothing is remembered', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });
    const { findByText } = render(EstimateBody, { props: { job, params: { jobId: '3' } } });
    expect(await findByText(/Estimate: EST-8-\d/)).toBeInTheDocument();
  });

  it('ignores a remembered doc id that is no longer in the job\'s estimate list', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });
    rememberSection('3', 'estimate', '999');
    const { findByText } = render(EstimateBody, { props: { job, params: { jobId: '3' } } });
    expect(await findByText(/Estimate: EST-8-\d/)).toBeInTheDocument();
  });

  it('normalizes the URL to the resolved doc via replaceState on a bare route', async () => {
    const e1 = est(7, 1);
    mockApi({ estimates: [e1], byId: { 7: e1 } });
    render(EstimateBody, { props: { job, params: { jobId: '3' } } });
    await waitFor(() => expect(window.location.hash).toBe('#/jobs/3/estimate/7'));
    expect(getJobWs('3').sections.estimate).toBe('7');
  });

  it('shows the gated empty state when the job has no estimates', async () => {
    // in_progress is past the quoting phase, so the empty state explains
    // instead of offering Start Estimate.
    mockApi({ estimates: [] });
    const { findByText, queryByRole } = render(EstimateBody, { props: { job, params: { jobId: '3' } } });
    expect(await findByText(/past the estimating phase/i)).toBeInTheDocument();
    expect(queryByRole('button', { name: /start estimate/i })).toBeNull();
  });
});

describe('EstimateBody doc-subnav navigation', () => {
  it('switches documents on a docId-only params change without touching the job', async () => {
    const e1 = est(7, 1);
    const e2 = est(8, 2);
    mockApi({ estimates: [e1, e2], byId: { 7: e1, 8: e2 } });
    const { findByText, rerender } = render(EstimateBody, { props: { job, params: { jobId: 3, docId: '7' } } });
    expect(await findByText(/Estimate: EST-7-\d/)).toBeInTheDocument();
    const listFetches = () => api.get.mock.calls.filter(([u]) => u.startsWith('/api/estimates/?job=')).length;
    await waitFor(() => expect(listFetches()).toBeGreaterThan(0));
    const listFetchesAfterFirstRender = listFetches();

    // Fresh params object, same jobId — what svelte-spa-router hands the
    // still-mounted workspace on every doc-subnav navigation.
    await rerender({ job, params: { jobId: 3, docId: '8' } });
    expect(await findByText(/Estimate: EST-8-\d/)).toBeInTheDocument();
    expect(jobFetches()).toHaveLength(0);
    // The document list follows the viewed document (as the old page did by
    // remounting), so a doc created-then-navigated-to is in the list. The
    // hosted panel requests the same URL for its subnav, so count relative to
    // the settled first render rather than absolutely.
    expect(listFetches()).toBeGreaterThan(listFetchesAfterFirstRender);
  });
});
