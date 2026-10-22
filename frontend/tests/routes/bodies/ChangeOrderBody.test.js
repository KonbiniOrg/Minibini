import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback,
}));
vi.mock('svelte-spa-router', () => ({ link: () => {}, push: vi.fn() }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import ChangeOrderBody from '@/routes/jobs/bodies/ChangeOrderBody.svelte';

// Ported from the retired JobChangeOrderPage tests. The shell-around-the-panel
// case now lives in tests/routes/JobWorkspace.test.js (change-order route).
const job = { job_id: 9, job_number: 'JOB-9', name: 'Widget', status: 'in_progress', contact: null, can_manage: true };

function co(id) {
  return {
    change_order_id: id, change_order_number: `CO-${id}`, job: 9,
    status: 'draft', can_manage: true, line_items: [],
  };
}

beforeEach(() => {
  user.set({ permissions: [] });
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    const m = url.match(/^\/api\/change-orders\/(\d+)\/$/);
    if (m) return Promise.resolve(co(Number(m[1])));
    if (url.includes('deliverables-baseline')) return Promise.resolve({ baseline: [] });
    if (url.startsWith('/api/change-orders/?job=')) return Promise.resolve({ results: [co(3), co(4)] });
    if (url.includes('/deliverables/')) return Promise.resolve([]);
    if (url.startsWith('/api/estimates/')) return Promise.resolve({ results: [] });
    return Promise.resolve({});
  });
});

describe('ChangeOrderBody', () => {
  it('renders the CO named by :coId and follows a coId-only params change without touching the job', async () => {
    const { container, findByText, rerender } = render(ChangeOrderBody, {
      props: { job, params: { jobId: '9', coId: '3' } },
    });
    await findByText('Line items');
    await waitFor(() => expect(within(container).queryByRole('heading', { level: 2 })).toHaveTextContent('CO-3'));

    // Fresh params object, same jobId — what svelte-spa-router hands the
    // still-mounted workspace on a subnav navigation.
    await rerender({ job, params: { jobId: '9', coId: '4' } });
    await waitFor(() => expect(within(container).queryByRole('heading', { level: 2 })).toHaveTextContent('CO-4'));
    expect(api.get.mock.calls.filter(([u]) => u === '/api/jobs/9/')).toHaveLength(0);
  });
});
