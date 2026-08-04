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
function mockApi(taskOverrides = {}) {
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
function mockApiWithJob(taskOverrides = {}, jobOverrides = {}, subtasks = []) {
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
    const { findByRole, findByText, queryByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await findByText('Sub A');
    expect(queryByText('edit')).toBeNull();
    expect(queryByText('del')).toBeNull();
    expect(queryByText('cancel')).toBeNull();
  });

  it('reorders subtasks via arrows posting to the job reorder endpoint', async () => {
    mockApiWithJob({ can_manage: true }, {}, subs);
    api.post.mockReset();
    api.post.mockResolvedValue({});
    const { findByRole, findByText, queryAllByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findTitle(findByRole);
    await findByText('Sub A');
    const downArrows = queryAllByText('▼');
    expect(downArrows.length).toBeGreaterThan(0);
    await fireEvent.click(downArrows[0]);
    expect(api.post).toHaveBeenCalledWith('/api/jobs/3/reorder-tasks/', {
      task_id: 8, direction: 'down',
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
