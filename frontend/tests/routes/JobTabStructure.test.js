import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));

import Router from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { jobWorkspaceRoutes } from '@/routes/jobs/jobWorkspaceRoutes.js';

// Every job tab shares one semantic structure (frontend/README.md → "Job
// tab structure"): a region labelled by the tab's <h2>, the h2 inside the
// region's <header> with the tab's actions, and no skipped heading levels
// from the job's <h1> down.

const baseJob = {
  job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
  contact: null, can_manage: true, materials: [], tasks: [],
};

const est = {
  estimate_id: 7, estimate_number: 'EST-7', job: 3, version: 1, status: 'draft',
  can_manage: true, is_amended: false, line_items: [], created_date: '2026-01-01T00:00:00Z',
  sent_date: null, expiration_date: null, closed_date: null,
};
const inv = {
  invoice_id: 7, invoice_number: 'INV-7', display_number: 'INV-7', job: 3, status: 'draft',
  created_date: '2026-01-01T00:00:00Z', sent_date: null, due_date: null, closed_date: null,
  is_late: false, qbo_id: null, qbo_payment_status: null, qbo_amount_paid: null,
  job_has_other_invoices: false, line_items: [],
};

function mockApi({ job = baseJob, estimates = [], invoices = [] } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/jobs/3/') return Promise.resolve({ ...job });
    if (url === '/api/jobs/3/overview/') return Promise.resolve({ due: null, spend: {}, work: {} });
    if (url.includes('deliverables-baseline')) return Promise.resolve({ baseline: [] });
    if (url.includes('/deliverables/')) return Promise.resolve([]);
    if (url.startsWith('/api/settings/')) return Promise.resolve({});
    if (url.startsWith('/api/shipments/')) return Promise.resolve([]);
    if (url.startsWith('/api/estimates/?job=')) return Promise.resolve({ results: estimates });
    if (url === '/api/estimates/7/') return Promise.resolve(est);
    if (url.startsWith('/api/invoices/?job=')) return Promise.resolve({ results: invoices });
    if (url === '/api/invoices/7/') return Promise.resolve(inv);
    const co = url.match(/^\/api\/change-orders\/(\d+)\/$/);
    if (co) return Promise.resolve({ change_order_id: Number(co[1]), change_order_number: `CO-${co[1]}`, job: 3, status: 'draft', can_manage: true, line_items: [] });
    if (url.startsWith('/api/jobs/3/history/')) return Promise.resolve({ results: [] });
    if (url === '/api/emails/?job=3') return Promise.resolve({ results: [] });
    return Promise.resolve({ results: [] });
  });
}

async function mountAt(hash) {
  window.location.hash = hash;
  const utils = render(Router, { props: { routes: jobWorkspaceRoutes } });
  await utils.findByText(/JOB #3/);
  return utils;
}

// Page headings in document order, ignoring open dialogs (a modal is its own
// document outline).
function headingLevels(container) {
  return [...container.querySelectorAll('h1, h2, h3, h4, h5, h6')]
    .filter((h) => !h.closest('[role="dialog"]'))
    .map((h) => Number(h.tagName[1]));
}

function expectNoSkippedLevels(container) {
  const levels = headingLevels(container);
  expect(levels[0]).toBe(1);
  for (let i = 1; i < levels.length; i++) {
    expect(levels[i] - levels[i - 1], `heading levels ${levels.join(',')}`).toBeLessThanOrEqual(1);
  }
  expect(levels.filter((l) => l === 1)).toHaveLength(1);
  expect(levels.filter((l) => l === 2)).toHaveLength(1);
}

const CASES = [
  { tab: 'overview', hash: '#/jobs/3', title: 'Overview' },
  { tab: 'estimate (document)', hash: '#/jobs/3/estimate/7', title: 'Estimate: EST-7-1', setup: { estimates: [est] }, action: 'Send Email' },
  { tab: 'estimate (none yet)', hash: '#/jobs/3/estimate', title: 'Estimates', setup: { job: { ...baseJob, status: 'draft' } }, emptyAction: 'Start Estimate' },
  { tab: 'change order', hash: '#/jobs/3/change-order/5', title: 'CO-5', action: 'Send to customer' },
  { tab: 'tasks', hash: '#/jobs/3/tasks', title: 'Tasks', action: 'Add Work' },
  { tab: 'invoice (document)', hash: '#/jobs/3/invoice/7', title: 'Invoice: INV-7', setup: { invoices: [inv] }, action: 'Send Invoice' },
  { tab: 'invoice (none yet)', hash: '#/jobs/3/invoice', title: 'Invoices', emptyAction: 'Start Invoice' },
  { tab: 'shipments', hash: '#/jobs/3/shipments', title: 'Shipments', action: '+ Add shipment' },
  { tab: 'pos', hash: '#/jobs/3/pos', title: 'Purchase orders' },
  { tab: 'emails', hash: '#/jobs/3/emails', title: 'Emails' },
  { tab: 'history', hash: '#/jobs/3/history', title: 'History' },
];

beforeEach(() => {
  localStorage.clear();
  user.set({ permissions: ['can_manage_jobs', 'can_manage_financials'] });
  window.location.hash = '';
});

describe('job tab structure', () => {
  it.each(CASES)('$tab: region labelled by its h2, actions in the header, no skipped levels', async ({ hash, title, setup, action, emptyAction }) => {
    mockApi(setup);
    const { container, findByRole } = await mountAt(hash);

    const region = await findByRole('region', { name: title });
    const header = region.querySelector(':scope > header');
    expect(header).not.toBeNull();
    expect(within(header).getByRole('heading', { level: 2, name: title })).toBeInTheDocument();

    if (action) {
      expect(within(header).getByRole('button', { name: action })).toBeInTheDocument();
    }
    if (emptyAction) {
      const empty = region.querySelector('.empty-state');
      expect(empty).not.toBeNull();
      expect(within(empty).getByRole('button', { name: emptyAction })).toBeInTheDocument();
    }

    await waitFor(() => expectNoSkippedLevels(container));
  });

  it('emails: shows the loading state until the fetch lands', async () => {
    mockApi();
    let resolveEmails;
    const base = api.get.getMockImplementation();
    api.get.mockImplementation((url) => {
      if (url === '/api/emails/?job=3') return new Promise((r) => { resolveEmails = r; });
      return base(url);
    });
    const { findByRole, findByText } = await mountAt('#/jobs/3/emails');
    const region = await findByRole('region', { name: 'Emails' });
    expect(within(region).getByText('Loading...')).toBeInTheDocument();
    resolveEmails({ results: [] });
    expect(await findByText(/No email linked to this job yet/)).toBeInTheDocument();
  });
});
