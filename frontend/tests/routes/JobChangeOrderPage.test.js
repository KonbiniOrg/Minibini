import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback,
}));
vi.mock('svelte-spa-router', () => ({ link: () => {}, push: vi.fn() }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobChangeOrderPage from '@/routes/jobs/JobChangeOrderPage.svelte';

const job = { job_id: 9, job_number: 'JOB-9', name: 'Widget', status: 'in_progress', contact: null, can_manage: true };

function co(id) {
  return {
    change_order_id: id, change_order_number: `CO-${id}`, job: 9,
    status: 'draft', can_manage: true, line_items: [],
  };
}

function mockApi() {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    const m = url.match(/^\/api\/change-orders\/(\d+)\/$/);
    if (m) return Promise.resolve(co(Number(m[1])));
    if (url.includes('deliverables-baseline')) return Promise.resolve({ baseline: [] });
    if (url.startsWith('/api/change-orders/?job=')) return Promise.resolve({ results: [co(3), co(4)] });
    if (url.includes('/deliverables/')) return Promise.resolve([]);
    if (url === '/api/jobs/9/') return Promise.resolve({ ...job });
    if (url.startsWith('/api/estimates/')) return Promise.resolve({ results: [] });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  user.set({ permissions: [] });
  mockApi();
});

describe('JobChangeOrderPage host', () => {
  it('renders the job shell (header + context band) around the CO panel', async () => {
    const { findByText, container } = render(JobChangeOrderPage, {
      props: { params: { jobId: '9', coId: '3' } },
    });
    // Shell chrome:
    await findByText(/JOB #9/);
    expect(container.querySelector('.context-band')).not.toBeNull();
    // Panel content ("CO-3" appears in both the subnav pill and the toolbar
    // title, so anchor on the title):
    await findByText('Line items');
    expect(container.querySelector('.page-title')).toHaveTextContent('CO-3');
  });

  it('does not refetch the job when only the coId param changes', async () => {
    const { container, findByText, rerender } = render(JobChangeOrderPage, {
      props: { params: { jobId: '9', coId: '3' } },
    });
    await findByText('Line items');
    await waitFor(() =>
      expect(container.querySelector('.page-title')).toHaveTextContent('CO-3'));
    const jobFetches = () =>
      api.get.mock.calls.filter(([u]) => u === '/api/jobs/9/').length;
    expect(jobFetches()).toBe(1);

    // Fresh params object, same jobId — what svelte-spa-router hands the
    // still-mounted component on a subnav navigation.
    await rerender({ params: { jobId: '9', coId: '4' } });
    await waitFor(() =>
      expect(container.querySelector('.page-title')).toHaveTextContent('CO-4'));
    expect(jobFetches()).toBe(1);
  });
});
