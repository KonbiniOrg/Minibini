import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, findByRole } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import LineItemForm from '@/components/purchaseorders/LineItemForm.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect units fetch (and others)
});

describe('LineItemForm', () => {
  it('submits a manual line with the quantity coerced to a number', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole } = render(LineItemForm, { props: { onSubmit, onCancel: vi.fn() } });

    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Bolt' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '3' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '2.50' } }); // not "From Inventory"
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    // type="number" inputs bind as numbers, so price arrives as 2.5 (not '2.50').
    expect(onSubmit).toHaveBeenCalledWith({
      description: 'Bolt', qty: 3, units: 'none', price: 2.5,
    });
  });

  it('submits a comment line with qty/price zeroed and no category field shown', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole, queryByLabelText } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Vendor lead time is 6 weeks' } });
    await fireEvent.click(getByLabelText(/Comment line/));
    expect(queryByLabelText(/Qty/)).toBeNull();
    expect(queryByLabelText(/^Price/)).toBeNull();
    expect(queryByLabelText(/Category/)).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({
      description: 'Vendor lead time is 6 weeks', is_comment: true, qty: 0, units: 'none', price: 0,
    });
  });

  it('switches to From Inventory mode', async () => {
    const { getByLabelText, queryByLabelText } = render(LineItemForm, { props: { onSubmit: vi.fn(), onCancel: vi.fn() } });
    // manual mode shows a Description field...
    expect(getByLabelText(/Description/)).toBeInTheDocument();
    await fireEvent.click(getByLabelText('From Inventory'));
    // ...pli mode hides it
    expect(queryByLabelText(/Description/)).toBeNull();
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(LineItemForm, { props: { onSubmit: vi.fn(), onCancel } });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('omits task when no task link was picked (unchanged payload shape)', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole } = render(LineItemForm, { props: { onSubmit, onCancel: vi.fn() } });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Bolt' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '3' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '2.50' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({
      description: 'Bolt', qty: 3, units: 'none', price: 2.5,
    });
  });

  it('does not show a Task Link picker until a job is picked (one Job picker feeds both)', async () => {
    const { queryByText, getByPlaceholderText } = render(LineItemForm, {
      props: { onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    expect(queryByText('Task Link (optional)')).toBeNull();
    // Exactly one Job picker on the consolidated form.
    expect(getByPlaceholderText('Search jobs…')).toBeInTheDocument();
  });

  it('submits the linked task id, WITHOUT job, when a task link is picked off the one Job picker', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/?')) {
        return Promise.resolve({ results: [{ job_id: 5, job_number: 'JOB-5', name: 'widget' }] });
      }
      if (url === '/api/jobs/5/tasks/') {
        return Promise.resolve([{ task_id: 10, name: 'Outsourced work' }]);
      }
      return Promise.resolve([]);
    });
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole, getByPlaceholderText, findByText, container } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Outsourced' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '50.00' } });

    // ONE Job picker on the consolidated form now, feeding both material
    // attribution and the task cascade.
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'wid' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: /JOB-5/ }));
    await new Promise((r) => setTimeout(r));

    // Task Link section appears once the job is picked. Filter-as-you-type
    // SearchPicker (fix 3), not a plain <select>.
    await findByText('Task Link (optional)');
    const taskInput = container.querySelector('input[placeholder="Search tasks…"]');
    await fireEvent.input(taskInput, { target: { value: 'Outsourced' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: 'Outsourced work' }));

    await findByText(/Cost will be attributed to this task/);

    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ task: 10 }));
    // Task implies its job -- `job` (and material_id) are withheld entirely.
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('job');
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('material_id');
  });

  it('job-only with "Create a new material" sends job (no material_id)', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/?')) return Promise.resolve({ results: [{ job_id: 5, job_number: 'JOB-5', name: 'widget' }] });
      if (url === '/api/jobs/5/') return Promise.resolve({ job_id: 5, materials: [] });
      return Promise.resolve([]);
    });
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole, getByPlaceholderText, container, findByText } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Bolt' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '3' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '2.50' } });
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'wid' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: /JOB-5/ }));
    await findByText(/No unordered materials on this job/);
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({
      description: 'Bolt', qty: 3, units: 'none', price: 2.5, job: 5,
    });
  });
});

describe('LineItemForm — material picker', () => {
  const JOB = { job_id: 5, materials: [
    { material_id: 41, description: '3/4 Baltic Birch', quantity: '4.00', units: 'sheet', item_code: 'BBPLY.75',
      inventory_item: 7, consumption_state: 'pending', po_line_item_id: null, cost_source: 'entered' },
    { material_id: 42, description: 'already ordered', quantity: '1.00', units: 'ea', item_code: 'X',
      inventory_item: 8, consumption_state: 'pending', po_line_item_id: 99, cost_source: 'po' },
    { material_id: 43, description: 'customer sends it', quantity: '1.00', units: 'ea', item_code: null,
      inventory_item: null, consumption_state: 'pending', po_line_item_id: null, cost_source: 'customer_supplied' },
    { material_id: 44, description: 'consumed', quantity: '1.00', units: 'ea', item_code: 'Y',
      inventory_item: 9, consumption_state: 'consumed', po_line_item_id: null, cost_source: 'entered' },
  ] };
  function mockJobs(jobs = { 5: JOB }) {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/?')) return Promise.resolve({ results: [
        { job_id: 5, job_number: 'JOB-5', name: 'widget' }, { job_id: 6, job_number: 'JOB-6', name: 'gadget' }] });
      const m = url.match(/^\/api\/jobs\/(\d+)\/$/);
      if (m) return Promise.resolve(jobs[m[1]] || { job_id: Number(m[1]), materials: [] });
      if (url === '/api/inventory/7/') return Promise.resolve({ inventory_item_id: 7, code: 'BBPLY.75', description: '3/4 Baltic Birch', units: 'sheet', purchase_price: '60.00' });
      return Promise.resolve([]);
    });
  }
  async function pickJob(container, getByPlaceholderText, label = /JOB-5/) {
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'g' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: label }));
    await new Promise((r) => setTimeout(r));
  }

  it('lists only pending, unlinked, non-customer materials plus "Create a new material"; nothing preselected; Add disabled', async () => {
    mockJobs();
    const { container, getByPlaceholderText, findByRole, getByRole, queryByText } = render(LineItemForm, {
      props: { onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    await pickJob(container, getByPlaceholderText);
    await findByRole('radio', { name: /BBPLY.75 · 4 sheet · 3\/4 Baltic Birch/ });
    expect([...container.querySelectorAll('input[name="material-choice"]')].map((r) => r.checked)).toEqual([false, false]);
    expect(queryByText(/already ordered/)).toBeNull();
    expect(queryByText(/customer sends it/)).toBeNull();
    expect(queryByText(/consumed/)).toBeNull();
    expect(getByRole('radio', { name: 'Create a new material for this line' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'Add' })).toBeDisabled();
  });

  it('picking a material in From Inventory mode sets and locks the item and sends material_id (no job)', async () => {
    mockJobs();
    const onSubmit = vi.fn();
    const { container, getByPlaceholderText, getByLabelText, findByRole, getByRole, findByText } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.click(getByLabelText('From Inventory'));
    await pickJob(container, getByPlaceholderText);
    await fireEvent.click(await findByRole('radio', { name: /BBPLY.75/ }));
    await findByText(/BBPLY.75 — 3\/4 Baltic Birch/);
    expect(container.querySelector('input[placeholder="Search inventory items…"]')).toBeNull();   // locked chip, no input
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '4' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({ inventory_item: 7, qty: 4, material_id: 41 });
  });

  it('in Manual mode a picked material links without touching the line fields', async () => {
    mockJobs();
    const onSubmit = vi.fn();
    const { container, getByPlaceholderText, getByLabelText, findByRole, getByRole } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'ply' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '4' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '58' } });
    await pickJob(container, getByPlaceholderText);
    await fireEvent.click(await findByRole('radio', { name: /BBPLY.75/ }));
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({ description: 'ply', qty: 4, units: 'none', price: 58, material_id: 41 });
  });

  it('shows the no-materials line and sends job when the job has nothing to attach to', async () => {
    mockJobs({ 5: { job_id: 5, materials: [] } });
    const onSubmit = vi.fn();
    const { container, getByPlaceholderText, getByLabelText, findByText, getByRole } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'ply' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '1' } });
    await pickJob(container, getByPlaceholderText);
    await findByText('No unordered materials on this job — a new material will be created.');
    expect(container.querySelector('input[name="material-choice"]')).toBeNull();
    expect(getByRole('button', { name: 'Add' })).toBeEnabled();
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ job: 5 }));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('material_id');
  });

  it('resets the material choice when the job changes', async () => {
    mockJobs();
    const { container, getByPlaceholderText, findByRole, getByRole, findByText } = render(LineItemForm, {
      props: { onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    await pickJob(container, getByPlaceholderText);
    await fireEvent.click(await findByRole('radio', { name: /BBPLY.75/ }));
    // clear and pick the other job
    await fireEvent.click(getByRole('button', { name: 'Clear' }));
    await pickJob(container, getByPlaceholderText, /JOB-6/);
    await findByText(/No unordered materials on this job/);
    expect(container.querySelector('input[name="material-choice"]:checked')).toBeNull();
  });

  it('the comment checkbox disables the Job picker and clears any job', async () => {
    mockJobs();
    const { container, getByPlaceholderText, getByLabelText, queryByText } = render(LineItemForm, {
      props: { onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    await pickJob(container, getByPlaceholderText);
    await fireEvent.click(getByLabelText(/Comment line/));
    expect(queryByText('Task Link (optional)')).toBeNull();
    expect(container.querySelector('input[placeholder="Search jobs…"]')).toBeDisabled();
  });
});
