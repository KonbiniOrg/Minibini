import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import TaskDetailPage from '@/routes/jobs/TaskDetailPage.svelte';

// The fetched task carries can_manage = "atom-holder OR this job's PM". The page
// gates its edit-task / assign affordances on task.can_manage alone (not the
// global atom). These tests set the global atom to false (worker) to prove the
// per-object flag is what drives the affordances.
function mockApi(taskOverrides = {}, deliverables = []) {
  const task = {
    task_id: 7, name: 'Mill', status: 'pending', job: { id: 3 },
    assignee_name: null, est_qty: '2', effective_rate: '25', unit_label: 'hr',
    ...taskOverrides,
  };
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/tasks/7/')) {
      if (url.includes('/materials')) return Promise.resolve([]);
      if (url.includes('/subtasks')) return Promise.resolve([]);
      return Promise.resolve(task);
    }
    // Checked before the generic '/api/jobs/3/' branch below — that prefix
    // would otherwise also swallow this more specific deliverables path.
    if (url.startsWith('/api/jobs/3/deliverables/')) return Promise.resolve(deliverables);
    if (url.startsWith('/api/jobs/3/')) return Promise.resolve({ job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress' });
    if (url.startsWith('/api/bleps/')) return Promise.resolve([]);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve([]);
    if (url.startsWith('/api/service-items/')) return Promise.resolve([]);
    if (url.startsWith('/api/contacts/')) return Promise.resolve({});
    return Promise.resolve([]);
  });
}

const findTitle = (f) => f('heading', { name: 'Mill' });

beforeEach(() => {
  // Worker (no atom): proves gating is driven by task.can_manage, not the atom.
  user.set({ id: 99, permissions: [] });
});

describe('TaskDetailPage header', () => {
  it('leads the title row with the task name and an activity pill', async () => {
    mockApi({ status: 'in_progress' });
    const { findByRole, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const pill = container.querySelector('.title-row .status-badge');
    expect(pill).toBeInTheDocument();
    expect(pill).toHaveClass('status-ongoing');
    expect(pill).toHaveTextContent('Ongoing');
  });

  it('links to the parent task when this is a subtask', async () => {
    mockApi({ parent_task: 4, parent_task_name: 'Build shelving unit' });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText(/subtask of/)).toBeInTheDocument();
    const parentLink = getByText('Build shelving unit');
    expect(parentLink.tagName).toBe('A');
    expect(parentLink.getAttribute('href')).toBe('/jobs/3/tasks/4');
  });

  it('shows no parent crumb on a top-level task', async () => {
    mockApi({ parent_task: null, parent_task_name: null });
    const { findByRole, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByText(/subtask of/)).toBeNull();
  });

  it('renders the blocked reason as a full-width line under the title row', async () => {
    mockApi({ status: 'blocked', blocked_reason: 'waiting on hardware delivery' });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText(/waiting on hardware delivery/)).toBeInTheDocument();
  });

  it('shows the INVOICED badge instead of the pill when the task is billed', async () => {
    mockApi({ status: 'complete', invoice: { id: 12, invoice_number: 'INV-12' } });
    const { findByRole, getByTitle, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByTitle(/billed on this invoice/i)).toBeInTheDocument();
    expect(container.querySelector('.title-row .status-badge')).toBeNull();
  });
});

describe('TaskDetailPage materials', () => {
  function mockWithMaterial(mat, taskOverrides = {}) {
    const task = {
      task_id: 7, name: 'Mill', status: 'complete', job: { id: 3 },
      ...taskOverrides,
    };
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/tasks/7/')) {
        if (url.includes('/materials')) return Promise.resolve([mat]);
        if (url.includes('/subtasks')) return Promise.resolve([]);
        return Promise.resolve(task);
      }
      if (url.startsWith('/api/jobs/3/')) return Promise.resolve({ job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress' });
      return Promise.resolve([]);
    });
  }

  it("puts a billed material's INVOICED badge in the status cell, not the description", async () => {
    // Shared MaterialRow contract: the badge rides the Status cell, same as
    // the job task list — never glued to the description text.
    mockWithMaterial({
      material_id: 1, description: 'Steel plate', quantity: '2', units: 'ea',
      consumption_state: 'consumed',
      invoice: { id: 12, invoice_number: 'INV-12' },
    });
    const { findByRole, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByRole('heading', { name: 'Mill' });
    await waitFor(() => expect(container.querySelector('.materials-table tbody tr')).not.toBeNull());
    const cells = container.querySelectorAll('.materials-table tbody tr td');
    const descCell = cells[0];
    expect(descCell).toHaveTextContent('Steel plate');
    expect(descCell.querySelector('.badge-invoiced')).toBeNull();
    const badgeCell = container.querySelector('.materials-table .badge-invoiced');
    expect(badgeCell).not.toBeNull();
  });

  it('keeps the header and body column counts aligned when a completed task has an invoiced material', async () => {
    mockWithMaterial({
      material_id: 1, description: 'Steel plate', quantity: '2', units: 'ea',
      invoice: { id: 12, invoice_number: 'INV-12' },
    });
    const { findByRole, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByRole('heading', { name: 'Mill' });
    await waitFor(() => expect(container.querySelector('.materials-table tbody tr')).not.toBeNull());
    const headCols = container.querySelectorAll('.materials-table thead th').length;
    const bodyCols = container.querySelectorAll('.materials-table tbody tr:first-child td').length;
    expect(bodyCols).toBe(headCols);
  });
});

describe('TaskDetailPage stat chips', () => {
  it('renders assignee, est time, est qty, actual, rate and charge chips', async () => {
    mockApi({
      status: 'in_progress', assignee_name: 'Dana',
      est_worker_time: '6:00:00', est_qty: '240',
      source_scheme_name: 'CNC', qty_source: 'entered_qty',
      unit_label: 'minute', actual_qty: '150',
      rate: '2.50', effective_rate: '2.50', computed_charge: '375.00',
    });
    const { findByRole, getByText, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText('Assignee')).toBeInTheDocument();
    expect(getByText('Dana')).toBeInTheDocument();
    expect(getByText('Est Time')).toBeInTheDocument();
    expect(getByText('6h 0m')).toBeInTheDocument();
    expect(getByText('Est Qty')).toBeInTheDocument();
    expect(getByText(/240 minute/)).toBeInTheDocument();
    expect(getByText('Actual')).toBeInTheDocument();
    expect(getByText(/150 minute/)).toBeInTheDocument();
    expect(getByText('Scheme')).toBeInTheDocument();
    expect(getByText('CNC')).toBeInTheDocument();
    expect(getByText('Rate')).toBeInTheDocument();
    expect(getByText('$2.50/minute')).toBeInTheDocument();
    expect(getByText('Charge')).toBeInTheDocument();
    expect(getByText('$375.00')).toBeInTheDocument();
    // Scheme is provenance, not itself a dollar amount — only Rate + Charge
    // carry the .money class.
    expect(container.querySelectorAll('.stat-chip.money')).toHaveLength(2);
  });

  it('renders a missing accounting_category as a dash, not an error (Phase 3: nullable end-to-end)', async () => {
    mockApi({
      status: 'in_progress', rate: '2.50', effective_rate: '2.50',
      unit_label: 'minute', accounting_category: null,
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const header = getByText('Category');
    const chip = header.closest('.stat-chip');
    expect(chip.querySelector('.stat-chip-body')).toHaveTextContent('—');
  });

  it('renders the accounting category label when set', async () => {
    mockApi({
      status: 'in_progress', rate: '2.50', effective_rate: '2.50',
      unit_label: 'minute', accounting_category: 5,
    });
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/accounting-categories/')) {
        return Promise.resolve([{ id: 5, code: 'LAB', name: 'Labor' }]);
      }
      if (url.startsWith('/api/tasks/7/')) {
        if (url.includes('/materials')) return Promise.resolve([]);
        if (url.includes('/subtasks')) return Promise.resolve([]);
        return Promise.resolve({
          task_id: 7, name: 'Mill', status: 'in_progress', job: { id: 3 },
          rate: '2.50', effective_rate: '2.50', unit_label: 'minute',
          accounting_category: 5,
        });
      }
      if (url.startsWith('/api/jobs/3/')) return Promise.resolve({ job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress' });
      if (url.startsWith('/api/bleps/')) return Promise.resolve([]);
      return Promise.resolve([]);
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const header = getByText('Category');
    const chip = header.closest('.stat-chip');
    expect(chip.querySelector('.stat-chip-body')).toHaveTextContent('LAB — Labor');
  });

  it('shows the Scheme chip as a dash when the task has money but its source preset is gone', async () => {
    // source_scheme is SET_NULL on preset delete — the task keeps its own
    // stamped rate/unit_label (still the price of record), just loses the
    // provenance name. Must render gracefully, not "null" or a crash.
    mockApi({
      status: 'pending', rate: '25', unit_label: 'hour', qty_source: 'elapsed_time',
      source_scheme_name: null, effective_rate: '25',
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const header = getByText('Scheme');
    const chip = header.closest('.stat-chip');
    expect(chip.querySelector('.stat-chip-body')).toHaveTextContent('—');
  });

  it('suppresses the duplicate Est Qty chip when it restates the worker time (hour-unit scheme)', async () => {
    mockApi({
      status: 'pending', est_worker_time: '2:00:00', est_qty: '2',
      source_scheme_name: 'Milling', qty_source: 'elapsed_time',
      unit_label: 'hour', rate: '25', effective_rate: '25',
    });
    const { findByRole, getByText, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText('Est Time')).toBeInTheDocument();
    expect(getByText('2h 0m')).toBeInTheDocument();
    expect(queryByText('Est Qty')).toBeNull();
  });

  it('shows both Est Time and Est Qty chips for a legacy row where they diverge', async () => {
    mockApi({
      status: 'pending', est_worker_time: '2:00:00', est_qty: '3',
      source_scheme_name: 'Milling', qty_source: 'elapsed_time',
      unit_label: 'hour', rate: '25', effective_rate: '25',
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText('Est Time')).toBeInTheDocument();
    expect(getByText('Est Qty')).toBeInTheDocument();
    expect(getByText(/3 hour/)).toBeInTheDocument();
  });

  it('the Actual chip shows the unit label with no literal "hour" fallback', async () => {
    mockApi({
      status: 'in_progress', source_scheme_name: 'Milling', qty_source: 'elapsed_time',
      unit_label: 'hour', rate: '25', actual_hours: '1.5', effective_rate: '25',
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText('Actual')).toBeInTheDocument();
    expect(getByText(/1.5 hour/)).toBeInTheDocument();
  });

  it('renders no money chips when the task has no rate scheme', async () => {
    mockApi({ rate: null, qty_source: null, effective_rate: null, unit_label: null, source_scheme_name: null, est_qty: null });
    const { findByRole, queryByText, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByText('Rate')).toBeNull();
    expect(queryByText('Charge')).toBeNull();
    expect(queryByText('Est Qty')).toBeNull();
    expect(queryByText('Scheme')).toBeNull();
    expect(container.querySelectorAll('.stat-chip.money')).toHaveLength(0);
  });

  it('opens the assign modal from the assignee name when can_manage', async () => {
    mockApi({ can_manage: true });
    const { findByRole, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const btn = getByRole('button', { name: 'Unassigned' });
    await fireEvent.click(btn);
    expect(getByRole('heading', { name: /assign/i })).toBeInTheDocument();
  });

  it('renders the assignee as plain text without can_manage', async () => {
    mockApi({ can_manage: false, assignee_name: 'Dana' });
    const { findByRole, getByText, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText('Dana')).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Dana' })).toBeNull();
  });
});

describe('TaskDetailPage action band', () => {
  it('shows Edit Task as a band button for any authenticated user', async () => {
    mockApi({ can_manage: false });
    const { findByRole, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByRole('button', { name: 'Edit Task' })).toBeInTheDocument();
  });

  it('hides Edit Task on a terminal task', async () => {
    mockApi({ status: 'complete' });
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Edit Task' })).toBeNull();
  });

  it('starts work from the action band', async () => {
    mockApi({ status: 'pending' });
    api.post.mockReset();
    api.post.mockResolvedValue({ status: 'ok', blep_id: 1 });
    const { findByRole, getByRole } = render(TaskDetailPage, {
      props: { params: { id: 3, taskId: 7 } },
    });
    await findTitle(findByRole);
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/7/start-work/', {});
  });

  it('shows no start/stop controls while the user bleps this task — the band is the stop surface', async () => {
    const { currentBlep } = await import('@/stores/currentBlep.js');
    currentBlep.set({
      id: 9, task: { id: 7, name: 'Mill' },
      start_time: new Date(Date.now() - 30 * 60000).toISOString(),
      blep_minimum_minutes: 1,
    });
    mockApi({ status: 'in_progress' });
    const { findByRole, queryByRole } = render(TaskDetailPage, {
      props: { params: { id: 3, taskId: 7 } },
    });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Start Work' })).toBeNull();
    expect(queryByRole('button', { name: 'Stop Work' })).toBeNull();
    currentBlep.set(null);
  });
});

// Deliverables bridge (spec §9 rule 7, task-owned-money Phase 4 Task 5):
// "Add as deliverable" copies this task's name/est_qty/unit_label into a new
// Deliverable. Top-level, quantity-bearing tasks only — hidden for subtasks
// (structures export from their parent) and once a link already exists
// (checked against the job's deliverables list, since the task payload
// itself carries no linked-deliverable indicator — Task 3 exposed none).
describe('TaskDetailPage add-as-deliverable bridge', () => {
  it('shows the button for a top-level, quantity-bearing, unlinked task', async () => {
    mockApi({ can_manage: true, parent_task: null, est_qty: '5' }, []);
    const { findByRole, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByRole('button', { name: 'Add as Deliverable' })).toBeInTheDocument();
  });

  it('hides the button on a subtask', async () => {
    mockApi({ can_manage: true, parent_task: 4, parent_task_name: 'Parent', est_qty: '5' }, []);
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Add as Deliverable' })).toBeNull();
  });

  it('hides the button when the task carries no est_qty', async () => {
    mockApi({ can_manage: true, parent_task: null, est_qty: null }, []);
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Add as Deliverable' })).toBeNull();
  });

  it('hides the button once a deliverable already links to this task', async () => {
    mockApi(
      { can_manage: true, parent_task: null, est_qty: '5' },
      [{ id: 1, source_task: 7, description: 'Mill', qty_ordered: '5', units: 'ea' }],
    );
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Add as Deliverable' })).toBeNull();
  });

  it('does not hide the button for a deliverable linked to a DIFFERENT task', async () => {
    mockApi(
      { can_manage: true, parent_task: null, est_qty: '5' },
      [{ id: 1, source_task: 99, description: 'Other', qty_ordered: '1', units: 'ea' }],
    );
    const { findByRole, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByRole('button', { name: 'Add as Deliverable' })).toBeInTheDocument();
  });

  it('hides the button when the task is not manageable by this user', async () => {
    mockApi({ can_manage: false, parent_task: null, est_qty: '5' }, []);
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Add as Deliverable' })).toBeNull();
  });

  it('posts to add-as-deliverable and refreshes the deliverables list on click', async () => {
    mockApi({ can_manage: true, parent_task: null, est_qty: '5' }, []);
    api.post.mockReset();
    api.post.mockResolvedValue({ id: 1, source_task: 7 });
    const { findByRole, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await fireEvent.click(getByRole('button', { name: 'Add as Deliverable' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/7/add-as-deliverable/', {});
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/jobs/3/deliverables/'));
    });
  });

  it('shows the global error overlay when the bridge call fails', async () => {
    mockApi({ can_manage: true, parent_task: null, est_qty: '5' }, []);
    api.post.mockReset();
    api.post.mockRejectedValue({ data: { detail: 'Already linked.' }, message: 'Already linked.' });
    const { findByRole, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await fireEvent.click(getByRole('button', { name: 'Add as Deliverable' }));
    await waitFor(() => {
      expect(get(overlayMessage)).toMatchObject({ kind: 'error', text: 'Already linked.' });
    });
    clearMessage();
  });
});

describe('TaskDetailPage section order', () => {
  it('runs Description → Subtasks → Materials → Work Sessions, with Add Entry available', async () => {
    mockApi({ description: 'Cut the panels' });
    const { findByRole, getByText, getByRole, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const headings = Array.from(container.querySelectorAll('h3')).map((h) => h.textContent);
    const idx = (t) => headings.findIndex((h) => h.includes(t));
    expect(idx('Description')).toBeGreaterThanOrEqual(0);
    expect(idx('Description')).toBeLessThan(idx('Subtasks'));
    expect(idx('Subtasks')).toBeLessThan(idx('Materials'));
    expect(idx('Materials')).toBeLessThan(idx('Work Sessions'));
    expect(getByText('Cut the panels')).toBeInTheDocument();
    // Logging forgotten historical time stays possible from this page.
    expect(getByRole('button', { name: 'Add Entry' })).toBeInTheDocument();
  });
});

describe('TaskDetailPage entered-qty add field', () => {
  const enteredQty = {
    qty_source: 'entered_qty', source_scheme_name: 'Press',
    unit_label: 'pcs', actual_qty: '9.00', status: 'in_progress',
  };

  beforeEach(() => {
    api.post.mockReset();
    api.post.mockResolvedValue({ actual_qty: '14.00' });
  });

  it('shows the running total with units in the Actual chip', async () => {
    mockApi(enteredQty);
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText('Actual')).toBeInTheDocument();
    expect(getByText(/9.00 pcs/)).toBeInTheDocument();
  });

  it('posts a signed add, clears the input and flashes the chip header', async () => {
    mockApi(enteredQty);
    const { findByRole, getByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const input = getByRole('spinbutton', { name: /add/i });
    await fireEvent.input(input, { target: { value: '-2' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/7/actual-qty/add/', { actual_qty: -2 });
    });
    await waitFor(() => expect(input.value).toBe(''));
    expect(getByText(/added/)).toBeInTheDocument();
  });

  it('never saves on blur — adds are not idempotent', async () => {
    mockApi(enteredQty);
    const { findByRole, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const input = getByRole('spinbutton', { name: /add/i });
    await fireEvent.input(input, { target: { value: '5' } });
    await fireEvent.blur(input);
    const addCalls = api.post.mock.calls.filter(([url]) => url.includes('actual-qty/add'));
    expect(addCalls).toHaveLength(0);
  });

  it('rejects a zero delta without posting', async () => {
    mockApi(enteredQty);
    const { findByRole, getByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await fireEvent.input(getByRole('spinbutton', { name: /add/i }), { target: { value: '0' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(getByText(/non-zero/i)).toBeInTheDocument();
    const addCalls = api.post.mock.calls.filter(([url]) => url.includes('actual-qty/add'));
    expect(addCalls).toHaveLength(0);
  });

  it('hides the add widget on a blocked task', async () => {
    mockApi({ ...enteredQty, status: 'blocked', blocked_reason: 'waiting' });
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('spinbutton', { name: /add/i })).toBeNull();
    expect(queryByRole('button', { name: 'Add' })).toBeNull();
  });
});

describe('TaskDetailPage prompt modals vs background refetch', () => {
  it('keeps an open prompt modal through a blep-change broadcast (no page blank)', async () => {
    // Real blepActivity store (not mocked): a broadcast (e.g. a band stop
    // finishing elsewhere) makes the page refetch. That refetch must NOT
    // blank the page ("Loading…") and remount TaskActions — that would
    // destroy any open prompt modal. Regression caught by driving the
    // real app; invariants documented in jobs-and-tasks §10.1a.
    mockApi({ qty_source: 'entered_qty', source_scheme_name: 'Press',
              unit_label: 'pcs', actual_qty: '9.00',
              status: 'in_progress' });
    api.post.mockReset();
    api.post.mockResolvedValue({ needs_actual_qty: true,
                                 unit_label: 'pcs', current_qty: '9.00' });
    const { findByRole, getByRole, findByRole: fbr, queryByText } = render(TaskDetailPage, {
      props: { params: { id: 3, taskId: 7 } },
    });
    await findTitle(findByRole);
    await fireEvent.click(getByRole('button', { name: 'Complete' }));
    await fbr('heading', { name: 'Settle up quantity' });
    const { notifyBlepChanged } = await import('@/stores/blepActivity.js');
    await notifyBlepChanged();
    await new Promise((r) => setTimeout(r, 100));
    expect(queryByText('Loading…')).toBeNull();
    expect(getByRole('heading', { name: 'Settle up quantity' })).toBeInTheDocument();
  });
});

describe('TaskDetailPage does not refetch in a loop', () => {
  it('fetch count stabilizes after load', async () => {
    // Regression: loadTask read `task` ($state) synchronously inside the
    // mount $effect, making the effect depend on `task` — which loadTask
    // itself reassigns → infinite refetch loop at network speed. The
    // mock stops answering after 20 task fetches so a looping page
    // fails the count assertion instead of starving the test runner.
    mockApi({ can_manage: true });
    const inner = api.get.getMockImplementation();
    let taskFetches = 0;
    api.get.mockImplementation((url) => {
      if (url === '/api/tasks/7/') {
        taskFetches += 1;
        if (taskFetches > 20) return new Promise(() => {});
      }
      return inner(url);
    });
    const { findByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await new Promise((r) => setTimeout(r, 250));
    expect(taskFetches).toBeLessThan(5);
  });
});

// Local mock allowing job overrides (on_hold) and subtasks.
function mockApiWithJob(taskOverrides = {}, jobOverrides = {}, subtasks = [], deliverables = []) {
  const task = {
    task_id: 7, name: 'Mill', status: 'pending', job: { id: 3 },
    assignee_name: null, est_qty: '2', effective_rate: '25', unit_label: 'hr',
    ...taskOverrides,
  };
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/tasks/7/')) {
      if (url.includes('/materials')) return Promise.resolve([]);
      if (url.includes('/subtasks')) return Promise.resolve(subtasks);
      return Promise.resolve(task);
    }
    if (url.startsWith('/api/tasks/')) {
      if (url.includes('/materials')) return Promise.resolve([]);
      return Promise.resolve({});
    }
    // Checked before the generic '/api/jobs/3/' branch below — that prefix
    // would otherwise also swallow this more specific deliverables path.
    if (url.startsWith('/api/jobs/3/deliverables/')) return Promise.resolve(deliverables);
    if (url.startsWith('/api/jobs/3/')) {
      return Promise.resolve({
        job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
        ...jobOverrides,
      });
    }
    if (url.startsWith('/api/bleps/')) return Promise.resolve([]);
    return Promise.resolve([]);
  });
}

describe('TaskDetailPage on-hold gating (B2)', () => {
  it('hides the action band, Edit Task, Add Subtask, and Add Material while held', async () => {
    mockApiWithJob({ can_manage: true, can_edit: true }, { on_hold: true, hold_reason: 'CO pending' });
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Start Work' })).toBeNull();
    expect(queryByRole('button', { name: /edit task/i })).toBeNull();
    expect(queryByRole('button', { name: /add subtask/i })).toBeNull();
    expect(queryByRole('button', { name: /add material/i })).toBeNull();
  });
});

describe('TaskDetailPage subtask tree (A3/B3)', () => {
  const subs = [
    { task_id: 8, name: 'Sub A', status: 'pending', parent_task: 7 },
    { task_id: 9, name: 'Sub B', status: 'pending', parent_task: 7 },
  ];

  it('offers no edit/del/cancel buttons on subtask rows', async () => {
    mockApiWithJob({ can_manage: true }, {}, subs);
    const { findByRole, findAllByText, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    // Two surfaces now name each subtask (the expected-vs-logged comparison
    // table + the passive tree below it) — findAll, not find, since a bare
    // name match is deliberately ambiguous.
    await findAllByText('Sub A');
    expect(queryByText('edit')).toBeNull();
    expect(queryByText('del')).toBeNull();
    expect(queryByText('cancel')).toBeNull();
  });

  it('reorders subtasks via arrows posting to the job reorder endpoint', async () => {
    mockApiWithJob({ can_manage: true }, {}, subs);
    api.post.mockReset();
    api.post.mockResolvedValue({});
    const { findByRole, findAllByText, queryAllByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await findAllByText('Sub A');
    const downArrows = queryAllByText('▼');
    expect(downArrows.length).toBeGreaterThan(0);
    await fireEvent.click(downArrows[0]);
    expect(api.post).toHaveBeenCalledWith('/api/jobs/3/reorder-tasks/', {
      task_id: 8, direction: 'down',
    });
  });
});

// Regression guard (task-owned-money Phase 4 Task 8 review): adding a
// subtask can flip THIS task's own `is_parent` (its first child) and
// `derived_unit_price`/`effective_rate` (every child) — all read off
// `task`, not `subtasks`. handleSubtaskSaved used to call loadSubtasks()
// only, leaving `task` stale until a manual page reload: Start Work stayed
// visible and the Rate chip kept showing the pre-structure value right
// after adding the very subtask that was supposed to change both.
describe('TaskDetailPage subtask-saved refresh (is_parent/derived state must not go stale)', () => {
  it('refetches the task (not just subtasks) after Add Subtask saves, and the UI reflects the new is_parent/derived-rate state without a reload', async () => {
    const scheme = {
      rate_scheme_id: 1, name: 'Laser preset', rate: '2.00', unit_label: 'min',
      accounting_category: null, modifiers: [],
    };
    // Flips once the subtask POST resolves — the mocked GET for the task
    // reflects "before" or "after" off this flag, the same way the real
    // backend would once the subtask actually exists.
    let subtaskAdded = false;
    const taskPayload = () => ({
      task_id: 7, name: 'Widgets', status: 'pending', job: { id: 3 },
      assignee_name: null, est_qty: '10', unit_label: 'ea', can_manage: true,
      rate: null,
      ...(subtaskAdded
        ? { is_parent: true, effective_rate: '34.00', derived_unit_price: '34.00' }
        : { is_parent: false, effective_rate: null, derived_unit_price: null }),
    });

    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === '/api/tasks/7/') return Promise.resolve(taskPayload());
      if (url.startsWith('/api/tasks/7/materials')) return Promise.resolve([]);
      if (url.startsWith('/api/tasks/7/subtasks')) return Promise.resolve([]);
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [scheme] });
      if (url.startsWith('/api/settings/')) return Promise.resolve({});
      if (url.startsWith('/api/jobs/3/deliverables/')) return Promise.resolve([]);
      if (url.startsWith('/api/jobs/3/')) {
        return Promise.resolve({ job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress' });
      }
      if (url.startsWith('/api/bleps/')) return Promise.resolve([]);
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve([]);
      if (url.startsWith('/api/service-items/')) return Promise.resolve([]);
      if (url.startsWith('/api/contacts/')) return Promise.resolve({});
      return Promise.resolve([]);
    });
    api.post.mockReset();
    api.post.mockImplementation((url) => {
      if (url === '/api/tasks/7/subtasks/') {
        subtaskAdded = true;
        return Promise.resolve({ task_id: 20, name: 'Laser cutting', parent_task: 7 });
      }
      return Promise.resolve({});
    });

    const { findByRole, getByRole, findByLabelText, getByLabelText, queryByRole }
      = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByRole('heading', { name: 'Widgets' });
    // Before: is_parent is false — Start Work is offered, no Rate chip yet.
    expect(getByRole('button', { name: 'Start Work' })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Unassigned' })).toBeInTheDocument();

    const taskCallsBeforeSave = api.get.mock.calls.filter((c) => c[0] === '/api/tasks/7/').length;

    await fireEvent.click(getByRole('button', { name: /add subtask/i }));
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Laser cutting' } });
    await fireEvent.click(getByRole('button', { name: 'Save', exact: true }));

    // The reload call: handleSubtaskSaved must issue an ADDITIONAL
    // /api/tasks/7/ fetch beyond whatever the dialog itself already caused
    // (WorkItemForm fetches the parent for its own preview) — this is the
    // exact call the pre-fix code skipped.
    await waitFor(() => {
      const after = api.get.mock.calls.filter((c) => c[0] === '/api/tasks/7/').length;
      expect(after).toBeGreaterThan(taskCallsBeforeSave);
    });

    // The rerender: Start Work disappears and the Rate chip picks up the
    // derived price — in place, with no page reload.
    await waitFor(() => expect(queryByRole('button', { name: 'Start Work' })).toBeNull());
    await waitFor(() => {
      const rateHeader = Array.from(document.querySelectorAll('.stat-chip-header'))
        .find((el) => el.textContent === 'Rate');
      expect(rateHeader).toBeTruthy();
      expect(rateHeader.closest('.stat-chip').querySelector('.stat-chip-body'))
        .toHaveTextContent('derived from children: $34.00/ea');
    });
  });
});

describe('TaskDetailPage can_edit gating (C1)', () => {
  it('hides Edit Task when can_edit is false', async () => {
    mockApiWithJob({ status: 'in_progress', can_manage: false, can_edit: false });
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: /edit task/i })).toBeNull();
  });

  it('shows Edit Task when can_edit is true', async () => {
    mockApiWithJob({ status: 'in_progress', can_edit: true });
    const { findByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(await findByRole('button', { name: /edit task/i })).toBeInTheDocument();
  });
});

describe('TaskDetailPage one-level subtask rule (B1)', () => {
  it('hides Add Subtask on a subtask (one level only)', async () => {
    mockApiWithJob({ parent_task: 4, parent_task_name: 'Build shelving unit' });
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: /add subtask/i })).toBeNull();
  });

  it('offers Add Subtask on a top-level task', async () => {
    mockApiWithJob({ parent_task: null });
    const { findByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(await findByRole('button', { name: /add subtask/i })).toBeInTheDocument();
  });
});

describe('TaskDetailPage subtask section suppression (one-level rule)', () => {
  it('shows no Subtasks section at all on a subtask', async () => {
    mockApiWithJob({ parent_task: 4, parent_task_name: 'Build shelving unit' });
    const { findByRole, queryByRole, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('heading', { name: /subtasks/i })).toBeNull();
    expect(queryByText('No subtasks.')).toBeNull();
  });

  it('keeps the Subtasks section on a top-level task', async () => {
    mockApiWithJob({ parent_task: null });
    const { findByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(await findByRole('heading', { name: /subtasks/i })).toBeInTheDocument();
  });
});

describe('TaskDetailPage crumbs', () => {
  it('offers no task-list link — the job nav rail covers it', async () => {
    mockApiWithJob({ parent_task: null });
    const { findByRole, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByText('task list')).toBeNull();
  });

  it('still links the parent from a subtask crumb', async () => {
    mockApiWithJob({ parent_task: 4, parent_task_name: 'Build shelving unit' });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const parentLink = getByText('Build shelving unit');
    expect(parentLink.tagName).toBe('A');
    expect(parentLink.getAttribute('href')).toBe('/jobs/3/tasks/4');
  });
});

// Quantity structure (spec §9, task-owned-money Phase 4 Task 4): a parent
// task (is_parent) prices from its children when it has no rate of its
// own — Task.effective_rate()/derived_unit_price() already compute this
// server-side; the page just needs to widen its money-block gate (today
// keyed on the task's OWN raw `rate`) and label the derived case.
describe('TaskDetailPage parent view — derived pricing', () => {
  it('labels the Rate chip "derived from children" for a rate-null parent', async () => {
    mockApi({
      status: 'pending', rate: null, is_parent: true,
      derived_unit_price: '12.50', effective_rate: '12.50', unit_label: 'ea',
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const header = getByText('Rate');
    const chip = header.closest('.stat-chip');
    expect(chip.querySelector('.stat-chip-body')).toHaveTextContent(/derived from children/i);
    expect(chip.querySelector('.stat-chip-body')).toHaveTextContent('$12.50/ea');
  });

  it('still shows Charge for a rate-null parent (money block gate widened beyond raw rate)', async () => {
    mockApi({
      status: 'pending', rate: null, is_parent: true,
      derived_unit_price: '12.50', effective_rate: '12.50', unit_label: 'ea',
      computed_charge: '25.00',
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByText('Charge')).toBeInTheDocument();
    expect(getByText('$25.00')).toBeInTheDocument();
  });

  it('shows the plain rate (no "derived" label) when a parent has an explicit rate override', async () => {
    mockApi({
      status: 'pending', rate: '99.00', is_parent: true,
      effective_rate: '99.00', unit_label: 'ea',
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const header = getByText('Rate');
    const chip = header.closest('.stat-chip');
    expect(chip.querySelector('.stat-chip-body')).not.toHaveTextContent(/derived from children/i);
    expect(chip.querySelector('.stat-chip-body')).toHaveTextContent('$99.00/ea');
  });

  // Regression guard: the template's trailing space in "derived from
  // children: " sits right at an {#if}/{/if} boundary, which Svelte's
  // whitespace-collapsing compiler can trim away entirely (it did, until
  // fixed with a &nbsp;) rather than merely collapsing a run of whitespace
  // — producing "derived from children:$12.50/ea" with NO space at all.
  // The two assertions above check "contains /derived from children/" and
  // "contains '$12.50/ea'" SEPARATELY, so neither one notices the missing
  // space between them; this test checks the two phrases adjacently, in a
  // single toHaveTextContent call, which fails if the space is gone.
  it('keeps a real space between "derived from children:" and the rate (adjacency, not just presence)', async () => {
    mockApi({
      status: 'pending', rate: null, is_parent: true,
      derived_unit_price: '12.50', effective_rate: '12.50', unit_label: 'ea',
    });
    const { findByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const header = getByText('Rate');
    const chip = header.closest('.stat-chip');
    // jest-dom's default normalizer collapses any run of Unicode whitespace
    // (which includes &nbsp;/ ) to a single ' ' before comparing, so
    // this passes with the &nbsp; fix and fails if the space is missing
    // entirely (as it was pre-fix): "children:$12.50" contains neither
    // "children: $12.50" nor a lone space between the two phrases.
    expect(chip.querySelector('.stat-chip-body'))
      .toHaveTextContent('derived from children: $12.50/ea');
  });
});

// Quantity structure (spec §9 rule 1): PM functions (start/blep/assign)
// delegate to a parent's children — the assign gesture must never render
// for one, since the server rejects setting a new assignee outright.
describe('TaskDetailPage non-startable parent affordances', () => {
  it('hides the assign button on a parent task, even with can_manage', async () => {
    mockApi({ can_manage: true, is_parent: true });
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Unassigned' })).toBeNull();
  });

  it('hides Start Work in the action band on a parent task', async () => {
    mockApi({ status: 'pending', is_parent: true });
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Start Work' })).toBeNull();
  });

  it('hides "Add Entry" (historical blep) on a parent task', async () => {
    mockApi({ status: 'pending', is_parent: true });
    const { findByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(queryByRole('button', { name: 'Add Entry' })).toBeNull();
  });

  it('keeps Start Work and Add Entry on a non-parent task', async () => {
    mockApi({ status: 'pending', is_parent: false });
    const { findByRole, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(getByRole('button', { name: 'Start Work' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'Add Entry' })).toBeInTheDocument();
  });
});

describe('TaskDetailPage parent completion offer (spec §9 rule 1)', () => {
  const openChild = { task_id: 8, name: 'Sub A', status: 'in_progress', parent_task: 7 };
  const terminalChild = { task_id: 9, name: 'Sub B', status: 'complete', parent_task: 7 };

  it('hides Complete and shows a note while children are not all terminal', async () => {
    mockApiWithJob({ status: 'in_progress', is_parent: true }, {}, [openChild]);
    const { findByRole, queryByRole, findAllByText, findByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await findAllByText(/Sub A/);
    expect(queryByRole('button', { name: 'Complete' })).toBeNull();
    expect(await findByText(/once every subtask/i)).toBeInTheDocument();
  });

  it('offers Complete once every child is terminal', async () => {
    mockApiWithJob({ status: 'in_progress', is_parent: true }, {}, [terminalChild]);
    const { findByRole, getByRole, findAllByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await findAllByText(/Sub B/);
    expect(getByRole('button', { name: 'Complete' })).toBeInTheDocument();
  });
});

describe('TaskDetailPage children table (expected vs logged)', () => {
  it('renders name, status, per-unit est, expected, and logged/actual for each child', async () => {
    const child = {
      task_id: 8, name: 'Per-widget polish', status: 'in_progress', parent_task: 7,
      est_qty: '2', expected_qty: '20', unit_label: 'ea', qty_source: 'entered_qty',
      actual_qty: '6', qty_scales_with_parent: true,
    };
    mockApiWithJob({ status: 'in_progress', is_parent: true }, {}, [child]);
    const { findByRole, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const table = await waitFor(() => {
      const t = container.querySelector('.children-table');
      expect(t).not.toBeNull();
      return t;
    });
    expect(table).toHaveTextContent('Per-widget polish');
    expect(table).toHaveTextContent('20'); // expected (derived)
    expect(table).toHaveTextContent('6');  // logged/actual
  });

  // Reviewer finding: Task._parent_multiplier() silently falls back to ×1
  // when a flag-true child's parent has no est_qty yet — the children
  // table must disclose that fallback (same carry-note WorkItemForm
  // already honors), never render a bare number that looks authoritative.
  it('discloses the ×1 fallback when a scaling child\'s parent has no est_qty', async () => {
    const child = {
      task_id: 8, name: 'Per-widget polish', status: 'in_progress', parent_task: 7,
      est_qty: '2', expected_qty: '2', unit_label: 'ea', qty_source: 'entered_qty',
      actual_qty: '0', qty_scales_with_parent: true,
    };
    mockApiWithJob({ status: 'in_progress', is_parent: true, est_qty: null }, {}, [child]);
    const { findByRole, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const table = await waitFor(() => {
      const t = container.querySelector('.children-table');
      expect(t).not.toBeNull();
      return t;
    });
    expect(table).toHaveTextContent(/parent quantity not set/i);
    expect(table).toHaveTextContent(/treated as ×1/i);
  });

  it('does not disclose anything for a flag-false (batch) child, even with no parent est_qty', async () => {
    const child = {
      task_id: 8, name: 'Batch cleanup', status: 'in_progress', parent_task: 7,
      est_qty: '5', expected_qty: '5', unit_label: 'ea', qty_source: 'entered_qty',
      actual_qty: '0', qty_scales_with_parent: false,
    };
    mockApiWithJob({ status: 'in_progress', is_parent: true, est_qty: null }, {}, [child]);
    const { findByRole, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const table = await waitFor(() => {
      const t = container.querySelector('.children-table');
      expect(t).not.toBeNull();
      return t;
    });
    expect(table).not.toHaveTextContent(/parent quantity not set/i);
  });

  it('does not disclose anything when the parent DOES have an est_qty', async () => {
    const child = {
      task_id: 8, name: 'Per-widget polish', status: 'in_progress', parent_task: 7,
      est_qty: '2', expected_qty: '20', unit_label: 'ea', qty_source: 'entered_qty',
      actual_qty: '0', qty_scales_with_parent: true,
    };
    mockApiWithJob({ status: 'in_progress', is_parent: true, est_qty: '10' }, {}, [child]);
    const { findByRole, container } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    const table = await waitFor(() => {
      const t = container.querySelector('.children-table');
      expect(t).not.toBeNull();
      return t;
    });
    expect(table).not.toHaveTextContent(/parent quantity not set/i);
  });
});

describe('TaskDetailPage materials use the shared task-list row (full action set)', () => {
  function mockMats(mats, taskOverrides = {}, jobOverrides = {}) {
    const task = {
      task_id: 7, name: 'Mill', status: 'in_progress', job: { id: 3 },
      can_manage: true, assignee_name: null, est_qty: '2',
      effective_rate: '25', unit_label: 'hr',
      ...taskOverrides,
    };
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/tasks/7/')) {
        if (url.includes('/materials')) return Promise.resolve(mats);
        if (url.includes('/subtasks')) return Promise.resolve([]);
        return Promise.resolve(task);
      }
      if (url.startsWith('/api/jobs/3/')) {
        return Promise.resolve({ job_id: 3, job_number: 'JOB-3', name: 'W',
                                 status: 'in_progress', ...jobOverrides });
      }
      return Promise.resolve([]);
    });
  }

  const needed = {
    material_id: 5, description: 'Baltic birch', quantity: '3',
    units: 'sheet', unit_cost: '40.00', sell_price: '55.00',
    consumption_state: 'pending', inventory_item: 7, qty_on_hand: '1.00',
    qty_available: '1.00', cost_source: 'entered',
  };

  it('renders the derived status chip on a material row', async () => {
    mockMats([needed]);
    const { findByRole, findByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(await findByText('Needed')).toBeInTheDocument();
  });

  it('offers the fulfillment actions (venue rule removed)', async () => {
    mockMats([needed]);
    const { findByRole, findByText, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(await findByText('Mark on-hand')).toBeInTheDocument();
    expect(queryByText('Attach expense')).toBeInTheDocument();
    expect(queryByText('draw more')).toBeInTheDocument();
    expect(queryByText('restock')).toBeInTheDocument();
    // Raw delete is gone — release (full-qty restock) is the removal path,
    // same vocabulary as the task list.
    expect(queryByText('del')).toBeNull();
  });

  it('shows a consumed material as finalized: Used chip, no actions', async () => {
    mockMats([{ ...needed, consumption_state: 'consumed' }]);
    const { findByRole, findByText, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    expect(await findByText('Used')).toBeInTheDocument();
    expect(queryByText('edit')).toBeNull();
    expect(queryByText('restock')).toBeNull();
    expect(queryByText('mark used')).toBeNull();
  });

  it('restock prompts for a quantity and posts to the restock endpoint', async () => {
    mockMats([needed]);
    api.post.mockReset();
    api.post.mockResolvedValue({});
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('3');
    const { findByRole, findByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await fireEvent.click(await findByText('restock'));
    expect(api.post).toHaveBeenCalledWith('/api/materials/5/restock/', { quantity: '3' });
    promptSpy.mockRestore();
  });

  it('freeze-plan-not-procurement still applies on a held job', async () => {
    mockMats([needed], {}, { on_hold: true, hold_reason: 'CO' });
    const { findByRole, findByText, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    // Procurement reality stays; plan edits freeze.
    expect(await findByText('Mark on-hand')).toBeInTheDocument();
    expect(queryByText('Attach expense')).toBeInTheDocument();
    expect(queryByText('restock')).toBeNull();
    expect(queryByText('edit')).toBeNull();
  });
});
