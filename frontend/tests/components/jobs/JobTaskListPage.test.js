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
import JobTaskListPage from '@/routes/jobs/JobTaskListPage.svelte';

const CATEGORIES = [
  { id: 1, code: 'RUSH', name: 'Rush Charges' },
  { id: 2, code: 'MISC', name: 'Miscellaneous' },
];

// The fetched job carries can_manage = "atom-holder OR this job's PM". The page
// toolbar gates "Mark Work Complete" on job.can_manage alone (not the global
// atom), while "Add Work" is open to any authenticated user on an unlocked job.
// These tests set the global atom to false (worker) to prove the per-object flag
// is what drives the manager affordance.
function mockApi(jobOverrides = {}, categoriesOverride = []) {
  const job = {
    job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
    contact: null, materials: [], tasks: [], fees: [],
    ...jobOverrides,
  };
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/jobs/3/')) return Promise.resolve(job);
    if (url.startsWith('/api/service-items/')) return Promise.resolve([]);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve(categoriesOverride);
    if (url.startsWith('/api/contacts/')) return Promise.resolve({});
    // /api/inventory/, /api/settings/, and anything else the picker or page needs
    return Promise.resolve([]);
  });
}

beforeEach(() => {
  // Worker (no atom): proves gating is driven by job.can_manage, not the atom.
  user.set({ id: 99, permissions: [] });
  clearMessage();
});

describe('JobTaskListPage per-job can_manage', () => {
  it('shows Add Work button even when atom off and can_manage false (add is open to all)', async () => {
    mockApi({ can_manage: false });
    const { getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await waitFor(() => expect(getByRole('button', { name: /add work/i })).toBeInTheDocument());
  });

  it('shows Mark Work Complete when can_manage is true (atom off)', async () => {
    mockApi({ can_manage: true });
    const { getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await waitFor(() => expect(getByRole('button', { name: /mark work complete/i })).toBeInTheDocument());
  });

  it('hides Mark Work Complete when can_manage is false (atom off)', async () => {
    mockApi({ can_manage: false });
    const { findByRole, queryByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    // wait for the toolbar to render (Add Work always shows on unlocked jobs)
    await findByRole('button', { name: /add work/i });
    expect(queryByRole('button', { name: /mark work complete/i })).toBeNull();
  });

  it('replaces the four granular add buttons with a single Add Work button', async () => {
    mockApi({ can_manage: false });
    const { findByRole, queryByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add work/i });
    expect(queryByRole('button', { name: /add fee/i })).toBeNull();
    expect(queryByRole('button', { name: /add manual task/i })).toBeNull();
    expect(queryByRole('button', { name: /add task from template/i })).toBeNull();
    expect(queryByRole('button', { name: /add material/i })).toBeNull();
  });
});

describe('JobTaskListPage — Add Work picker → FeeModal path', () => {
  it('shows the Add Work toolbar button', async () => {
    mockApi({ can_manage: false });
    const { findByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    expect(await findByRole('button', { name: /add work/i })).toBeInTheDocument();
  });

  it('clicking Add Work opens the picker dialog', async () => {
    mockApi({ can_manage: false });
    const { findByRole, getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => expect(getByRole('dialog')).toBeInTheDocument());
  });

  it('freeform Add Task path opens the manual task form seeded with the typed name', async () => {
    mockApi({ can_manage: false });
    const { findByRole, getByRole, getByPlaceholderText, getByDisplayValue } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => getByRole('dialog'));
    await fireEvent.input(getByPlaceholderText(/search services or materials/i), { target: { value: 'Custom milling' } });
    await fireEvent.click(await findByRole('button', { name: /add task/i }));
    // WorkItemForm manual create mode opens, name seeded from the typed text.
    await waitFor(() => getByRole('heading', { name: /add manual task/i }));
    await waitFor(() => expect(getByDisplayValue('Custom milling')).toBeInTheDocument());
  });

  it('freeform fee path through picker opens FeeModal', async () => {
    mockApi({ can_manage: false });
    const { findByRole, getByRole, getByPlaceholderText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => getByRole('dialog'));
    await fireEvent.input(getByPlaceholderText(/search services or materials/i), { target: { value: 'Rush' } });
    // task-list footer offers an explicit "Add Fee" button
    const freeformBtn = await findByRole('button', { name: /add fee/i });
    await fireEvent.click(freeformBtn);
    // FeeModal opens (picker closes, FeeModal renders h3 "Add Fee")
    await waitFor(() => expect(getByRole('heading', { name: /add fee/i })).toBeInTheDocument());
  });

  it('FeeModal seeded from picker receives the job id (posts to correct endpoint)', async () => {
    api.post.mockResolvedValue({});
    mockApi({ can_manage: false });
    const { findByRole, getByRole, getByLabelText, getByPlaceholderText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => getByRole('dialog'));
    await fireEvent.input(getByPlaceholderText(/search services or materials/i), { target: { value: 'Rush' } });
    await fireEvent.click(await findByRole('button', { name: /add fee/i }));
    await waitFor(() => getByRole('heading', { name: /add fee/i }));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/3/fees/', expect.any(Object));
  });

  it('FeeModal receives non-empty categories when categories are loaded', async () => {
    mockApi({ can_manage: false }, CATEGORIES);
    const { findByRole, getByRole, getByLabelText, getByPlaceholderText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add work/i });
    await fireEvent.click(getByRole('button', { name: /add work/i }));
    await waitFor(() => getByRole('dialog'));
    await fireEvent.input(getByPlaceholderText(/search services or materials/i), { target: { value: 'Rush' } });
    await fireEvent.click(await findByRole('button', { name: /add fee/i }));
    await waitFor(() => getByRole('heading', { name: /add fee/i }));
    const select = getByLabelText(/Accounting Category/i);
    // Two real options plus "-- None --" placeholder
    expect(select.options.length).toBe(3);
    expect(select.options[1].text).toContain('RUSH');
  });
});

describe('JobTaskListPage — action failures go to the global overlay', () => {
  it('raises the overlay when Mark Work Complete fails', async () => {
    mockApi({ can_manage: true });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.post.mockRejectedValueOnce(Object.assign(new Error('Request failed'), {
      status: 400, data: { detail: 'Tasks are still open.' },
    }));
    const { findByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await fireEvent.click(await findByRole('button', { name: /mark work complete/i }));
    await waitFor(() => expect(get(overlayMessage)).toEqual({
      kind: 'error', text: 'Tasks are still open.',
    }));
    confirmSpy.mockRestore();
  });
});

describe('JobTaskListPage — material fulfillment actions', () => {
  // A job with one in-progress task carrying a single pending material. The
  // material's fields drive its derived status (materialStatus.js).
  function mockJobWithMaterial(material, { drafts = [] } = {}) {
    const job = {
      job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
      contact: null, materials: [], fees: [], can_manage: true,
      tasks: [{ task_id: 10, name: 'Cut', status: 'in_progress', parent_task: null }],
    };
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/3/')) return Promise.resolve(job);
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
    mockJobWithMaterial(neededMat, { drafts: [] });
    api.post.mockResolvedValueOnce({ po_id: 9, po_number: 'PO-2026-0007' });
    const { findByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await fireEvent.click(await findByRole('button', { name: 'Order' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/55/order/', {}));
    await waitFor(() => expect(get(overlayMessage)).toEqual({
      kind: 'success', text: 'Added to',
      link: { href: '#/purchase-orders/9', label: 'PO-2026-0007' },
    }));
  });

  it('Order with drafts opens the chooser and posts the picked po_id', async () => {
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    mockJobWithMaterial(neededMat, {
      drafts: [{ po_id: 5, po_number: 'PO-5', business_name: 'Acme' }],
    });
    api.post.mockResolvedValueOnce({ po_number: 'PO-5' });
    const { findByRole, getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await fireEvent.click(await findByRole('button', { name: 'Order' }));
    // chooser dialog lists the draft with its vendor
    await waitFor(() => getByRole('dialog'));
    await fireEvent.click(await findByRole('button', { name: /PO-5 — Acme/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/55/order/', { po_id: 5 }));
  });

  it('a draft with no vendor renders "no vendor"', async () => {
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    mockJobWithMaterial(neededMat, {
      drafts: [{ po_id: 6, po_number: 'PO-6', business_name: null }],
    });
    const { findByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await fireEvent.click(await findByRole('button', { name: 'Order' }));
    expect(await findByRole('button', { name: /PO-6 — no vendor/ })).toBeInTheDocument();
  });

  it('Mark received opens a qty prompt and POSTs mark-on-hand', async () => {
    user.set({ id: 1, permissions: [] });
    const customerMat = {
      ...neededMat, material_id: 77, cost_source: 'customer_supplied',
    };
    mockJobWithMaterial(customerMat);
    api.post.mockResolvedValueOnce({});
    const { findByRole, getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await fireEvent.click(await findByRole('button', { name: 'Mark received' }));
    const dialog = await waitFor(() => getByRole('dialog'));
    // defaults to the shortfall (4 needed − 0 on hand)
    expect(within(dialog).getByLabelText(/quantity received/i).value).toBe('4');
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Mark received' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/77/mark-on-hand/', { quantity: '4' }));
  });
});

describe('JobTaskListPage — fees display', () => {
  it('lists a job fee by description', async () => {
    mockApi({
      can_manage: false,
      fees: [{ fee_id: 10, description: 'Setup Charge', quantity: '2', unit_rate: '50', sort_order: 1 }],
    });
    const { findByText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    expect(await findByText('Setup Charge')).toBeInTheDocument();
  });

  it('does not render the fees section when there are no fees', async () => {
    mockApi({ can_manage: false, fees: [] });
    const { findByRole, queryByText } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await findByRole('button', { name: /add work/i });
    expect(queryByText('Fees')).toBeNull();
  });
});
