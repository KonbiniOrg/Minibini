import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import TasksPanel from '@/components/tasks/TasksPanel.svelte';

// The job carries can_manage = "atom-holder OR this job's PM". The panel
// toolbar gates "Mark Work Complete" on job.can_manage alone (not the global
// atom), while "Add Work" is open to any authenticated user on an unlocked job.
// These tests set the global atom to false (worker) to prove the per-object flag
// is what drives the manager affordance.
function makeJob(overrides = {}) {
  return {
    job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
    contact: null, materials: [], tasks: [],
    ...overrides,
  };
}

function mockApi(categoriesOverride = []) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/service-items/')) return Promise.resolve([]);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve(categoriesOverride);
    // /api/expenses/, /api/settings/, and anything else the picker or panel needs
    return Promise.resolve([]);
  });
}

beforeEach(() => {
  // Worker (no atom): proves gating is driven by job.can_manage, not the atom.
  user.set({ id: 99, permissions: [] });
  clearMessage();
});

describe('TasksPanel per-job can_manage', () => {
  it('shows Add Work button even when atom off and can_manage false (add is open to all)', async () => {
    mockApi();
    const { getByRole } = render(TasksPanel, { props: { job: makeJob({ can_manage: false }) } });
    await waitFor(() => expect(getByRole('button', { name: /add work/i })).toBeInTheDocument());
  });

  it('shows Mark Work Complete when can_manage is true (atom off)', async () => {
    mockApi();
    const { getByRole } = render(TasksPanel, { props: { job: makeJob({ can_manage: true }) } });
    await waitFor(() => expect(getByRole('button', { name: /mark work complete/i })).toBeInTheDocument());
  });

  it('hides Mark Work Complete when can_manage is false (atom off)', async () => {
    mockApi();
    const { findByRole, queryByRole } = render(TasksPanel, { props: { job: makeJob({ can_manage: false }) } });
    // wait for the toolbar to render (Add Work always shows on unlocked jobs)
    await findByRole('button', { name: /add work/i });
    expect(queryByRole('button', { name: /mark work complete/i })).toBeNull();
  });

  it('replaces the four granular add buttons with a single Add Work button', async () => {
    mockApi();
    const { findByRole, queryByRole } = render(TasksPanel, { props: { job: makeJob({ can_manage: false }) } });
    await findByRole('button', { name: /add work/i });
    expect(queryByRole('button', { name: /add fee/i })).toBeNull();
    expect(queryByRole('button', { name: /add manual task/i })).toBeNull();
    expect(queryByRole('button', { name: /add task from template/i })).toBeNull();
    expect(queryByRole('button', { name: /add material/i })).toBeNull();
  });
});

describe('TasksPanel — Add Work picker', () => {
  it('shows the Add Work toolbar button', async () => {
    mockApi();
    const { findByRole } = render(TasksPanel, { props: { job: makeJob({ can_manage: false }) } });
    expect(await findByRole('button', { name: /add work/i })).toBeInTheDocument();
  });

  it('clicking Add Work opens the picker dialog', async () => {
    mockApi();
    const { findByRole, getByRole } = render(TasksPanel, { props: { job: makeJob({ can_manage: false }) } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => expect(getByRole('dialog')).toBeInTheDocument());
  });

  it('freeform Add Task path opens the manual task form seeded with the typed name', async () => {
    mockApi();
    const { findByRole, getByRole, getByPlaceholderText, getByDisplayValue } = render(TasksPanel, { props: { job: makeJob({ can_manage: false }) } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => getByRole('dialog'));
    await fireEvent.input(getByPlaceholderText(/search services or materials/i), { target: { value: 'Custom milling' } });
    await fireEvent.click(await findByRole('button', { name: /add task/i }));
    // WorkItemForm manual create mode opens, name seeded from the typed text.
    await waitFor(() => getByRole('heading', { name: /add manual task/i }));
    await waitFor(() => expect(getByDisplayValue('Custom milling')).toBeInTheDocument());
  });

  it('a service item the live search found but the cached template list lacks opens the form intact', async () => {
    // Cross-window repro: the item was created in another window AFTER this
    // panel loaded its templates list, so the mount-time list is stale but the
    // picker's live search finds it. The pick must carry the full object —
    // the form may not re-resolve it from the stale cached list.
    const fresh = {
      template_id: 77, template_name: 'Laser Etch', description: 'etch it',
      rate_scheme: 4,
      rate_scheme_detail: { rate_scheme_id: 4, name: 'Shop', rate: '90.00', unit_label: 'hour' },
      default_active_modifiers: [],
    };
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/service-items/') && url.includes('search=')) {
        return Promise.resolve([fresh]);          // live search: finds it
      }
      if (url.startsWith('/api/service-items/')) return Promise.resolve([]); // stale mount-time list
      return Promise.resolve([]);
    });
    const { findByRole, getByRole, getByPlaceholderText, getAllByDisplayValue } =
      render(TasksPanel, { props: { job: makeJob({ can_manage: false }) } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => getByRole('dialog'));
    await fireEvent.input(getByPlaceholderText(/search services or materials/i),
      { target: { value: 'Laser' } });
    // SearchPicker rows select on mousedown (beats the input's blur).
    await fireEvent.mouseDown(await findByRole('button', { name: /laser etch/i }));
    // Template form opens with the picked item selected AND its defaults
    // applied: both the template <select> and the name <input> show it.
    await waitFor(() => getByRole('heading', { name: /add task from template/i }));
    await waitFor(() =>
      expect(getAllByDisplayValue('Laser Etch').length).toBeGreaterThanOrEqual(2));
  });

  it('the picker offers no fee path from the task surface', async () => {
    // Fees are gone (better-fees, 2026-08): after typing, the footer offers
    // exactly Add Task / Add Material — no Add Fee, and no modal path to one.
    mockApi();
    const { findByRole, getByRole, getByPlaceholderText, queryByRole } = render(TasksPanel, { props: { job: makeJob({ can_manage: false }) } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => getByRole('dialog'));
    await fireEvent.input(getByPlaceholderText(/search services or materials/i), { target: { value: 'Rush' } });
    await findByRole('button', { name: /add task/i });
    expect(getByRole('button', { name: /add material/i })).toBeInTheDocument();
    expect(queryByRole('button', { name: /add fee/i })).toBeNull();
  });
});

describe('TasksPanel — action failures go to the global overlay', () => {
  it('raises the overlay when Mark Work Complete fails', async () => {
    mockApi();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.post.mockRejectedValueOnce(Object.assign(new Error('Request failed'), {
      status: 400, data: { detail: 'Tasks are still open.' },
    }));
    const { findByRole } = render(TasksPanel, { props: { job: makeJob({ can_manage: true }) } });
    await fireEvent.click(await findByRole('button', { name: /mark work complete/i }));
    await waitFor(() => expect(get(overlayMessage)).toEqual({
      kind: 'error', text: 'Tasks are still open.',
    }));
    confirmSpy.mockRestore();
  });
});

describe('TasksPanel — material fulfillment actions', () => {
  // A job with one in-progress task carrying a single pending material. The
  // material's fields drive its derived status (materialStatus.js).
  function jobWithMaterial() {
    return makeJob({
      can_manage: true,
      tasks: [{ task_id: 10, name: 'Cut', status: 'in_progress', parent_task: null }],
    });
  }

  function mockApiWithMaterial(material, { drafts = [] } = {}) {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === '/api/tasks/10/materials/') return Promise.resolve([material]);
      if (url === '/api/tasks/10/subtasks/') return Promise.resolve([]);
      if (url.startsWith('/api/purchase-orders/')) return Promise.resolve(drafts);
      if (url.startsWith('/api/service-items/')) return Promise.resolve([]);
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve([]);
      return Promise.resolve([]);
    });
  }

  const neededMat = {
    material_id: 55, description: 'Steel', quantity: '4', sell_price: '5', units: 'kg',
    consumption_state: 'pending', inventory_item: 7, cost_source: 'entered',
    qty_on_hand: '0', po_line_item_id: null, po_number: null, job: 3, task: 10,
  };

  it('Order with zero drafts POSTs immediately and links to the PO', async () => {
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    mockApiWithMaterial(neededMat, { drafts: [] });
    api.post.mockResolvedValueOnce({ po_id: 9, po_number: 'PO-2026-0007' });
    const { findByRole } = render(TasksPanel, { props: { job: jobWithMaterial() } });
    await fireEvent.click(await findByRole('button', { name: 'Order' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/55/order/', {}));
    await waitFor(() => expect(get(overlayMessage)).toEqual({
      kind: 'success', text: 'Added to',
      link: { href: '#/purchase-orders/9', label: 'PO-2026-0007' },
    }));
  });

  it('Order with drafts opens the chooser and posts the picked po_id', async () => {
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    mockApiWithMaterial(neededMat, {
      drafts: [{ po_id: 5, po_number: 'PO-5', business_name: 'Acme' }],
    });
    api.post.mockResolvedValueOnce({ po_number: 'PO-5' });
    const { findByRole, getByRole } = render(TasksPanel, { props: { job: jobWithMaterial() } });
    await fireEvent.click(await findByRole('button', { name: 'Order' }));
    // chooser dialog lists the draft with its vendor
    await waitFor(() => getByRole('dialog'));
    await fireEvent.click(await findByRole('button', { name: /PO-5 — Acme/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/55/order/', { po_id: 5 }));
  });

  it('a draft with no vendor renders "no vendor"', async () => {
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    mockApiWithMaterial(neededMat, {
      drafts: [{ po_id: 6, po_number: 'PO-6', business_name: null }],
    });
    const { findByRole } = render(TasksPanel, { props: { job: jobWithMaterial() } });
    await fireEvent.click(await findByRole('button', { name: 'Order' }));
    expect(await findByRole('button', { name: /PO-6 — no vendor/ })).toBeInTheDocument();
  });

  it('Mark received opens a qty prompt and POSTs mark-on-hand', async () => {
    user.set({ id: 1, permissions: [] });
    const customerMat = {
      ...neededMat, material_id: 77, cost_source: 'customer_supplied',
    };
    mockApiWithMaterial(customerMat);
    api.post.mockResolvedValueOnce({});
    const { findByRole, getByRole } = render(TasksPanel, { props: { job: jobWithMaterial() } });
    await fireEvent.click(await findByRole('button', { name: 'Mark received' }));
    const dialog = await waitFor(() => getByRole('dialog'));
    // defaults to the shortfall (4 needed − 0 on hand)
    expect(within(dialog).getByLabelText(/quantity received/i).value).toBe('4');
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Mark received' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/77/mark-on-hand/', { quantity: '4' }));
  });
});

describe('TasksPanel — job-change coupling', () => {
  // Old JobTaskListPage's `reload()` was `loadJob()`: every mutation refetched
  // the job (and, with it, its nested tasks/materials) from the server.
  // The panel no longer owns the job fetch, so that same "mutate → refresh
  // job-derived state" coupling must now run through `onJobChange` — proving
  // the parent's job refetch is still what's triggered on a job-level action.
  it('calls onJobChange after Mark Work Complete succeeds', async () => {
    mockApi();
    api.post.mockResolvedValueOnce({});
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onJobChange = vi.fn().mockResolvedValue();
    const job = makeJob({ can_manage: true });
    const { findByRole } = render(TasksPanel, { props: { job, onJobChange } });
    await fireEvent.click(await findByRole('button', { name: /mark work complete/i }));
    await waitFor(() => expect(onJobChange).toHaveBeenCalled());
    confirmSpy.mockRestore();
  });
});

describe('TasksPanel on-hold gating (B2)', () => {
  it('hides Add Work while the job is held, keeps Add Expense', async () => {
    mockApi();
    const { findByRole, queryByRole } = render(TasksPanel, {
      props: { job: makeJob({ on_hold: true }) },
    });
    await findByRole('button', { name: /add expense/i });
    expect(queryByRole('button', { name: /add work/i })).toBeNull();
  });

  it('hides the work-complete button while held, even for managers', async () => {
    mockApi();
    const { findByRole, queryByRole } = render(TasksPanel, {
      props: { job: makeJob({ can_manage: true, on_hold: true }) },
    });
    await findByRole('button', { name: /add expense/i });
    expect(queryByRole('button', { name: /work complete|check complete/i })).toBeNull();
  });
});

describe('TasksPanel Check Complete (B4)', () => {
  it('labels the button Check Complete when an open task exists', async () => {
    mockApi();
    const job = makeJob({
      can_manage: true,
      tasks: [{ task_id: 1, name: 'Open', status: 'pending', parent_task: null }],
    });
    const { findByRole, queryByRole } = render(TasksPanel, { props: { job } });
    await findByRole('button', { name: /check complete/i });
    expect(queryByRole('button', { name: /mark work complete/i })).toBeNull();
  });

  it('labels the button Check Complete when a loose pending material exists', async () => {
    mockApi();
    const job = makeJob({
      can_manage: true,
      tasks: [{ task_id: 1, name: 'Done', status: 'complete', parent_task: null }],
      materials: [{ material_id: 5, description: 'Loose', quantity: '2',
                    consumption_state: 'pending', task: null }],
    });
    const { findByRole } = render(TasksPanel, { props: { job } });
    await findByRole('button', { name: /check complete/i });
  });

  it('labels the button Mark Work Complete when everything is final', async () => {
    mockApi();
    const job = makeJob({
      can_manage: true,
      tasks: [{ task_id: 1, name: 'Done', status: 'complete', parent_task: null }],
    });
    const { findByRole } = render(TasksPanel, { props: { job } });
    await findByRole('button', { name: /mark work complete/i });
  });

  it('Check Complete posts without confirm and lists the blockers', async () => {
    mockApi();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.post.mockReset();
    api.post.mockResolvedValue({
      blockers: {
        tasks: [{ task_id: 1, name: 'Open', status: 'pending' }],
        materials: [{ material_id: 5, description: 'Loose stock', task_id: null }],
      },
    });
    const job = makeJob({
      can_manage: true,
      tasks: [{ task_id: 1, name: 'Open', status: 'pending', parent_task: null }],
    });
    const { findByRole, findByText } = render(TasksPanel, { props: { job } });
    const button = await findByRole('button', { name: /check complete/i });
    await fireEvent.click(button);
    expect(api.post).toHaveBeenCalledWith('/api/jobs/3/work-complete/', {});
    expect(confirmSpy).not.toHaveBeenCalled();
    await findByText(/resolve/i);
    await findByText('Loose stock');
    confirmSpy.mockRestore();
  });
});
