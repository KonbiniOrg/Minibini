import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import DeliverablesSection from '@/components/jobs/DeliverablesSection.svelte';

function mockApi({ items = [], editable = false } = {}) {
  api.get.mockImplementation((url) => {
    if (url.endsWith('/editability/')) return Promise.resolve({ editable, reason: null });
    return Promise.resolve(items);
  });
}

beforeEach(() => {
  api.get.mockReset();
});

describe('DeliverablesSection', () => {
  it('loads and lists deliverables', async () => {
    mockApi({ items: [{ qty_ordered: '10.00', units: 'ea', description: 'Widget' }] });
    const { findByText } = render(DeliverablesSection, { props: { jobId: 5 } });
    expect(await findByText('Widget')).toBeInTheDocument();
    expect(await findByText('10')).toBeInTheDocument(); // trailing zeros trimmed
  });

  it('shows the empty state', async () => {
    mockApi({ items: [] });
    const { findByText } = render(DeliverablesSection, { props: { jobId: 5 } });
    expect(await findByText(/No deliverables yet/)).toBeInTheDocument();
  });

  it('offers Edit when the user can manage and the list is editable', async () => {
    mockApi({ items: [{ qty_ordered: '1', units: 'ea', description: 'X' }], editable: true });
    const { findByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    expect(await findByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  it('hides Edit when the user cannot manage, even if editable', async () => {
    mockApi({ items: [{ qty_ordered: '1', units: 'ea', description: 'X' }], editable: true });
    const { findByText, queryByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: false } });
    await findByText('X'); // wait for load to settle
    expect(queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
  });

  it('hides Edit when not editable, even if the user can manage', async () => {
    mockApi({ items: [{ qty_ordered: '1', units: 'ea', description: 'X' }], editable: false });
    const { findByText, queryByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    await findByText('X'); // wait for load to settle
    expect(queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
  });
});

// Deliverables bridge (spec §9 rule 7, task-owned-money Phase 4 Task 5):
// provenance link + "Create work structure" on unlinked rows + a passive
// mismatch badge (task est_qty vs qty_ordered — deliberately NOT actuals).
describe('DeliverablesSection deliverables bridge', () => {
  beforeEach(() => {
    user.set({ permissions: [] });
  });

  it('links an unlinked row\'s "Create work structure" to the task, once created', async () => {
    mockApi({
      items: [{ id: 1, qty_ordered: '5', units: 'ea', description: 'Widget', source_task: null, source_task_name: null }],
    });
    const { findByText, getByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    await findByText('Widget');
    expect(getByRole('button', { name: 'Create work structure' })).toBeInTheDocument();
  });

  it('shows the provenance link and hides "Create work structure" once linked', async () => {
    mockApi({
      items: [{
        id: 1, qty_ordered: '5', units: 'ea', description: 'Widget',
        source_task: 7, source_task_name: 'Mill widgets', source_task_est_qty: '5.00',
      }],
    });
    const { findByRole, queryByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    const provenanceLink = await findByRole('link', { name: 'Mill widgets' });
    expect(provenanceLink).toHaveAttribute('href', '/jobs/5/tasks/7');
    expect(queryByRole('button', { name: 'Create work structure' })).not.toBeInTheDocument();
  });

  it('hides "Create work structure" without CanManageJobOrPM or financials', async () => {
    mockApi({
      items: [{ id: 1, qty_ordered: '5', units: 'ea', description: 'Widget', source_task: null }],
    });
    const { findByText, queryByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: false } });
    await findByText('Widget');
    expect(queryByRole('button', { name: 'Create work structure' })).not.toBeInTheDocument();
  });

  it('offers "Create work structure" to a financials-only user even without job can_manage', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi({
      items: [{ id: 1, qty_ordered: '5', units: 'ea', description: 'Widget', source_task: null }],
    });
    const { findByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: false } });
    expect(await findByRole('button', { name: 'Create work structure' })).toBeInTheDocument();
  });

  it('hides "Create work structure" while the job is on hold', async () => {
    mockApi({
      items: [{ id: 1, qty_ordered: '5', units: 'ea', description: 'Widget', source_task: null }],
    });
    const { findByText, queryByRole } = render(
      DeliverablesSection, { props: { jobId: 5, canManage: true, jobOnHold: true } },
    );
    await findByText('Widget');
    expect(queryByRole('button', { name: 'Create work structure' })).not.toBeInTheDocument();
  });

  it('shows a mismatch badge when the linked task\'s est_qty differs from qty_ordered', async () => {
    mockApi({
      items: [{
        id: 1, qty_ordered: '5', units: 'ea', description: 'Widget',
        source_task: 7, source_task_name: 'Mill widgets', source_task_est_qty: '8.00',
      }],
    });
    const { findByText } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    expect(await findByText(/mismatch/i)).toBeInTheDocument();
  });

  it('shows no mismatch badge when the linked task\'s est_qty matches qty_ordered', async () => {
    mockApi({
      items: [{
        id: 1, qty_ordered: '5', units: 'ea', description: 'Widget',
        source_task: 7, source_task_name: 'Mill widgets', source_task_est_qty: '5.00',
      }],
    });
    const { findByText, queryByText } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    await findByText('Mill widgets');
    expect(queryByText(/mismatch/i)).not.toBeInTheDocument();
  });

  it('shows no mismatch badge when the linked task carries no est_qty', async () => {
    mockApi({
      items: [{
        id: 1, qty_ordered: '5', units: 'ea', description: 'Widget',
        source_task: 7, source_task_name: 'Mill widgets', source_task_est_qty: null,
      }],
    });
    const { findByText, queryByText } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    await findByText('Mill widgets');
    expect(queryByText(/mismatch/i)).not.toBeInTheDocument();
  });

  it('posts to create-work-structure and reloads on click', async () => {
    mockApi({
      items: [{ id: 1, qty_ordered: '5', units: 'ea', description: 'Widget', source_task: null }],
    });
    api.post.mockReset();
    api.post.mockResolvedValue({ task_id: 42 });
    const { findByRole } = render(DeliverablesSection, { props: { jobId: 5, canManage: true } });
    const btn = await findByRole('button', { name: 'Create work structure' });
    await fireEvent.click(btn);
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/deliverables/1/create-work-structure/', {});
    await waitFor(() => {
      // load() re-fetches the list — at least 2 GET rounds on the base URL.
      expect(api.get.mock.calls.filter(([u]) => u === '/api/jobs/5/deliverables/').length).toBeGreaterThan(1);
    });
  });
});
