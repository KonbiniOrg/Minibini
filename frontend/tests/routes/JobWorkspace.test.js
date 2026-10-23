import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, within, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));

import Router from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { jobWorkspaceRoutes } from '@/routes/jobs/jobWorkspaceRoutes.js';
import { rememberBand, getJobWs } from '@/stores/jobWorkspace.js';

const job = {
  job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
  contact: null, can_manage: true, materials: [], tasks: [],
};

function mockApi() {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/jobs/3/') return Promise.resolve({ ...job });
    if (url === '/api/jobs/3/overview/') return Promise.resolve({ due: null, spend: {}, work: {} });
    if (url.includes('/deliverables/')) return Promise.resolve([]);
    if (url.startsWith('/api/settings/')) return Promise.resolve({});
    if (url.startsWith('/api/shipments/')) return Promise.resolve([]);
    if (url.startsWith('/api/service-items/') || url.startsWith('/api/accounting-categories/')) return Promise.resolve([]);
    if (url.startsWith('/api/jobs/3/history/')) return Promise.resolve({ results: [
      { id: 1, entry_type: 'note', object_type: 'job', object_id: 3,
        username: 'admin', timestamp: '2026-01-03T10:00:00Z', text: 'Customer called',
        changes: null, source_label: 'Job JOB-3', source_link: '#/jobs/3' },
    ] });
    if (url === '/api/emails/?job=3') return Promise.resolve({ results: [
      { email_record_id: 9, direction: 'inbound', display_address: 'a@b.com',
        created_at: '2026-01-01T00:00:00Z', temp_email: { subject: 'Hello there' } },
    ] });
    return Promise.resolve({ results: [] });
  });
}

const jobFetches = () => api.get.mock.calls.filter(([url]) => url === '/api/jobs/3/');

// The real router against the real job route table. These tests pin the one
// property the workspace exists for (issue #511): switching sections keeps
// the shell (header + band + rail) mounted and does not refetch the job.
async function mountAt(hash) {
  window.location.hash = hash;
  const utils = render(Router, { props: { routes: jobWorkspaceRoutes } });
  await utils.findByText(/JOB #3/);
  return utils;
}

async function navigate(hash) {
  window.location.hash = hash;
  await waitFor(() => expect(window.location.hash).toBe(hash));
}

beforeEach(() => {
  mockApi();
  user.set({ permissions: ['can_manage_jobs'] });
  window.location.hash = '';
});

describe('JobWorkspace routing (persistent shell)', () => {
  it('keeps the same rail DOM node across a section switch; revalidates the job silently', async () => {
    const deliverableFetches = () => api.get.mock.calls.filter(([u]) => u === '/api/jobs/3/deliverables/');
    const { container, findByRole, queryByText } = await mountAt('#/jobs/3/tasks');
    const railBefore = container.querySelector('.job-nav-rail');
    expect(railBefore).toBeInTheDocument();
    expect(railBefore.querySelector('.rail-link.active').dataset.section).toBe('tasks');
    expect(jobFetches()).toHaveLength(1);
    await waitFor(() => expect(deliverableFetches()).toHaveLength(1));

    await navigate('#/jobs/3/history');
    await findByRole('button', { name: /^summary$/i });

    const railAfter = container.querySelector('.job-nav-rail');
    expect(railAfter).toBe(railBefore);
    expect(railBefore.isConnected).toBe(true);
    expect(railAfter.querySelector('.rail-link.active').dataset.section).toBe('history');
    expect(queryByText('Loading...')).not.toBeInTheDocument();
    // The job IS re-requested (freshness), but the payload was identical, so
    // no new job object was handed down: the band's deliverables (keyed on job
    // identity) did not reload.
    await waitFor(() => expect(jobFetches()).toHaveLength(2));
    expect(deliverableFetches()).toHaveLength(1);
  });

  it('applies a changed job in place on a section switch (no remount, no placeholder)', async () => {
    const { container, findByText, queryByText } = await mountAt('#/jobs/3/tasks');
    const rail = container.querySelector('.job-nav-rail');
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/3/') return Promise.resolve({ ...job, name: 'Renamed Widget', status: 'work_complete' });
      if (url.includes('/deliverables/')) return Promise.resolve([]);
      return Promise.resolve({ results: [] });
    });
    await navigate('#/jobs/3/history');
    expect(await findByText(/Renamed Widget/)).toBeInTheDocument();
    expect(container.querySelector('.job-nav-rail')).toBe(rail);
    expect(queryByText('Loading...')).not.toBeInTheDocument();
  });

  it('overview → section keeps the shell too (the :id vs :jobId route forms)', async () => {
    const { container, findByText } = await mountAt('#/jobs/3');
    await findByText('Scope');
    const header = container.querySelector('.job-nav-rail');

    await navigate('#/jobs/3/shipments');
    await waitFor(() =>
      expect(container.querySelector('.rail-link.active').dataset.section).toBe('shipments'));

    expect(container.querySelector('.job-nav-rail')).toBe(header);
  });

  it('change-order route: shell around the CO panel, rail shows Estimates active', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/3/') return Promise.resolve({ ...job });
      const m = url.match(/^\/api\/change-orders\/(\d+)\/$/);
      if (m) return Promise.resolve({ change_order_id: Number(m[1]), change_order_number: `CO-${m[1]}`, job: 3, status: 'draft', can_manage: true, line_items: [] });
      if (url.includes('deliverables-baseline')) return Promise.resolve({ baseline: [] });
      if (url.includes('/deliverables/')) return Promise.resolve([]);
      return Promise.resolve({ results: [] });
    });
    const { container, findByText } = await mountAt('#/jobs/3/change-order/5');
    expect(container.querySelector('.context-band')).not.toBeNull();
    expect(container.querySelector('.rail-link.active').dataset.section).toBe('estimate');
    await findByText('Line items');
    await waitFor(() => expect(within(container).queryByRole('heading', { level: 2 })).toHaveTextContent('CO-5'));
  });

  it('refetches when the job itself changes', async () => {
    api.get.mockImplementation((url) => {
      const m = url.match(/^\/api\/jobs\/(\d+)\/$/);
      if (m) return Promise.resolve({ ...job, job_id: Number(m[1]), job_number: `JOB-${m[1]}` });
      if (url.includes('/overview/')) return Promise.resolve({ due: null, spend: {}, work: {} });
      if (url.includes('/deliverables/')) return Promise.resolve([]);
      return Promise.resolve({ results: [] });
    });
    const { findByText } = await mountAt('#/jobs/3/tasks');
    await navigate('#/jobs/4/tasks');
    await findByText(/JOB #4/);
    expect(api.get.mock.calls.filter(([url]) => url === '/api/jobs/4/')).toHaveLength(1);
  });

  it('re-reads per-job shell state when the job changes (band collapse is per job)', async () => {
    api.get.mockImplementation((url) => {
      const m = url.match(/^\/api\/jobs\/(\d+)\/$/);
      if (m) return Promise.resolve({ ...job, job_id: Number(m[1]), job_number: `JOB-${m[1]}` });
      if (url.includes('/deliverables/')) return Promise.resolve([]);
      return Promise.resolve({ results: [] });
    });
    rememberBand('4', 'collapsed');
    const { container, findByText } = await mountAt('#/jobs/3/tasks');
    expect(container.querySelector('.context-band.collapsed')).toBeNull();

    await navigate('#/jobs/4/tasks');
    await findByText(/JOB #4/);
    await waitFor(() => expect(container.querySelector('.context-band.collapsed')).toBeInTheDocument());
  });
});

// Ported from the retired per-section glue-page tests: each section route
// renders the shell (header + rail) around its panel, both historical param
// forms resolve, and a failed job fetch shows the error text.
describe('JobWorkspace sections', () => {
  it('tasks: shell + tasks panel', async () => {
    const { container, findByRole } = await mountAt('#/jobs/3/tasks');
    expect(container.querySelector('.job-nav-rail')).toBeInTheDocument();
    expect(await findByRole('button', { name: /add work/i })).toBeInTheDocument();
  });

  it('tasklist (legacy alias): resolves to the tasks section', async () => {
    const { container, findByRole } = await mountAt('#/jobs/3/tasklist');
    expect(container.querySelector('.rail-link.active').dataset.section).toBe('tasks');
    expect(await findByRole('button', { name: /add work/i })).toBeInTheDocument();
  });

  it('shipments: shell + shipments panel', async () => {
    const { findByText } = await mountAt('#/jobs/3/shipments');
    expect(await findByText('This job has no deliverables yet. Add deliverables to the job before shipping.')).toBeInTheDocument();
  });

  it('pos: shell + job-filtered PO panel', async () => {
    const { findByText } = await mountAt('#/jobs/3/pos');
    expect(await findByText('No purchase orders touch this job yet. Order its materials from Purchasing.')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/purchase-orders/?job=3');
  });

  it('history (legacy :id route form): shell + history section with its tabs', async () => {
    const { container, findByRole, findByText } = await mountAt('#/jobs/3/history');
    expect(container.querySelector('.rail-link.active').dataset.section).toBe('history');
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(await findByRole('button', { name: 'Timeline' }));
    expect(await findByText('Customer called')).toBeInTheDocument();
  });

  it('emails: shell + the full-width email panel in the page body', async () => {
    const { container } = await mountAt('#/jobs/3/emails');
    // The context band hosts its own EmailPanel too, so scope to the body.
    await waitFor(() => {
      const pageBody = container.querySelector('.page-body');
      expect(pageBody && within(pageBody).queryByText('Hello there')).toBeTruthy();
    });
    expect(api.get).toHaveBeenCalledWith('/api/emails/?job=3');
  });

  it('estimate/:docId: the docId param reaches the estimate body (rail shows Estimates)', async () => {
    const est = { estimate_id: 7, estimate_number: 'EST-7', job: 3, version: 1, status: 'draft',
      can_manage: true, is_amended: false, line_items: [], created_date: '2026-01-01T00:00:00Z',
      sent_date: null, expiration_date: null, closed_date: null };
    const base = api.get.getMockImplementation();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/estimates/?job=')) return Promise.resolve({ results: [est] });
      if (url === '/api/estimates/7/') return Promise.resolve(est);
      return base(url);
    });
    const { container, findByText } = await mountAt('#/jobs/3/estimate/7');
    expect(container.querySelector('.rail-link.active').dataset.section).toBe('estimate');
    expect(await findByText(/Estimate: EST-7-\d/)).toBeInTheDocument();
  });

  it('invoice/:docId: the docId param reaches the invoice body (rail shows Invoices)', async () => {
    const inv = { invoice_id: 7, invoice_number: 'INV-7', display_number: 'INV-7', job: 3, status: 'draft',
      created_date: '2026-01-01T00:00:00Z', sent_date: null, due_date: null, closed_date: null,
      is_late: false, qbo_id: null, qbo_payment_status: null, qbo_amount_paid: null,
      job_has_other_invoices: false, line_items: [] };
    const base = api.get.getMockImplementation();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/invoices/?job=')) return Promise.resolve({ results: [inv] });
      if (url === '/api/invoices/7/') return Promise.resolve(inv);
      return base(url);
    });
    const { container, findByText } = await mountAt('#/jobs/3/invoice/7');
    expect(container.querySelector('.rail-link.active').dataset.section).toBe('invoice');
    expect(await findByText('Invoice: INV-7')).toBeInTheDocument();
  });

  it('switching sections never hands the new body the previous section\'s docId', async () => {
    // The section is derived from $location while svelte-spa-router delivers
    // the matched params a tick later. If the two are read from different
    // sources, the invoice body can mount with the estimate's docId: a wrong
    // /api/invoices/7/ fetch and the wrong id remembered for the section.
    const est = { estimate_id: 7, estimate_number: 'EST-7', job: 3, version: 1, status: 'draft',
      can_manage: true, is_amended: false, line_items: [], created_date: '2026-01-01T00:00:00Z',
      sent_date: null, expiration_date: null, closed_date: null };
    const inv = { invoice_id: 9, invoice_number: 'INV-9', display_number: 'INV-9', job: 3, status: 'draft',
      created_date: '2026-01-01T00:00:00Z', sent_date: null, due_date: null, closed_date: null,
      is_late: false, qbo_id: null, qbo_payment_status: null, qbo_amount_paid: null,
      job_has_other_invoices: false, line_items: [] };
    const base = api.get.getMockImplementation();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/estimates/?job=')) return Promise.resolve({ results: [est] });
      if (url === '/api/estimates/7/') return Promise.resolve(est);
      if (url.startsWith('/api/invoices/?job=')) return Promise.resolve({ results: [inv] });
      if (url === '/api/invoices/9/') return Promise.resolve(inv);
      return base(url);
    });
    const { findByText } = await mountAt('#/jobs/3/estimate/7');
    expect(await findByText(/Estimate: EST-7-\d/)).toBeInTheDocument();

    await navigate('#/jobs/3/invoice/9');
    expect(await findByText('Invoice: INV-9')).toBeInTheDocument();

    expect(api.get.mock.calls.filter(([u]) => u === '/api/invoices/7/')).toHaveLength(0);
    expect(getJobWs('3').sections.invoice).toBe('9');
    expect(getJobWs('3').sections.estimate).toBe('7');
  });

  it('shows the error text when the job fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    window.location.hash = '#/jobs/3/tasks';
    const { findByText } = render(Router, { props: { routes: jobWorkspaceRoutes } });
    expect(await findByText('boom')).toBeInTheDocument();
  });
});
