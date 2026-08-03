import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Error',
}));

import { api } from '@/lib/api.js';
import WorkItemForm from '@/components/WorkItemForm.svelte';

const HOURLY_SCHEME = { rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hour', modifiers: [], accounting_category: 3 };
const FLAT_FEE_SCHEME = { rate_scheme_id: 2, name: 'Quick Fix', algorithm: 'percentage', rate: '150', unit_label: 'none', modifiers: [] };
const HOUR_UNIT_SCHEME = { rate_scheme_id: 7, name: 'CNC Hourly', algorithm: 'elapsed_time', rate: '90', unit_label: 'hour', modifiers: [] };
const EACH_SCHEME = { rate_scheme_id: 8, name: 'Widget', algorithm: 'entered_qty', rate: '10', unit_label: 'ea', modifiers: [] };
const CATEGORIES = [{ id: 3, code: 'LABOR', name: 'Labor' }, { id: 4, code: 'MATL', name: 'Materials' }];

// Routes api.get by URL prefix so the two parallel fetches (schemes,
// settings) each get the right shape — a single blanket mockResolvedValue
// no longer works now that onMount fires both.
function mockGet({ schemes = [HOURLY_SCHEME, FLAT_FEE_SCHEME], defaultRateScheme = '' } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: schemes });
    if (url.startsWith('/api/settings/')) return Promise.resolve({ default_rate_scheme: defaultRateScheme });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  mockGet();
  api.post.mockReset();
  api.post.mockResolvedValue({});
  api.patch = vi.fn().mockResolvedValue({});
});

describe('WorkItemForm', () => {
  it('also POSTs a ServiceItem when "Save to catalog" is checked (manual create)', async () => {
    const onSaved = vi.fn();
    const { findByLabelText, getByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, onSaved },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Custom Polish' } });
    await fireEvent.click(getByLabelText(/save to catalog/i));
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    // Task should be POSTed to the job-task endpoint
    const taskCalls = api.post.mock.calls.filter((c) => c[0] === '/api/jobs/5/tasks/');
    expect(taskCalls.length).toBe(1);
    // Catalog item should also be created
    const catalogCalls = api.post.mock.calls.filter((c) => c[0] === '/api/service-items/');
    expect(catalogCalls.length).toBe(1);
    expect(catalogCalls[0][1]).toEqual(expect.objectContaining({ template_name: 'Custom Polish' }));
    expect(String(catalogCalls[0][1].rate_scheme)).toBe('1');
  });

  it('does not show "Save to catalog" when editing', async () => {
    const { queryByLabelText, findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: { name: 'X', active_modifiers: [], est_qty: '1', rate: '25', unit_label: 'hour', can_manage: true } },
    });
    expect(queryByLabelText(/save to catalog/i)).not.toBeInTheDocument();
    // HOURLY_SCHEME (the shop's most common scheme) is hour-unit: a single
    // "Estimated hours" input, prefilled from est_qty since this legacy row
    // has no est_worker_time, and no separate "Estimated qty" input.
    expect(await findByLabelText(/Estimated hours/)).toHaveValue('1');
    expect(queryByLabelText(/Estimated qty/)).not.toBeInTheDocument();
  });

  it('selects the preset template in the pulldown (template mode)', async () => {
    const templates = [
      { template_id: 5, template_name: 'CNC Routing', rate_scheme: 1 },
      { template_id: 6, template_name: 'Sanding', rate_scheme: 1 },
    ];
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'template', context: 'job', contextId: 5, templates, presetTemplateId: 5 },
    });
    const select = await findByLabelText(/template/i);
    // Was blank before the fix (numeric option value vs stringified preset).
    expect(select.value).toBe('5');
  });

  it('pre-fills the name from presetName on a manual (custom-task) create', async () => {
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, presetName: 'Special weld' },
    });
    expect(await findByLabelText(/Name/)).toHaveValue('Special weld');
  });

  it('requires a name', async () => {
    const { findByRole, getByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    await fireEvent.click(await findByRole('button', { name: 'Save' }));
    expect(getByText('Name is required.')).toBeInTheDocument();
  });

  it('labels the rate-scheme selector as "Rate Scheme"', async () => {
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    expect(await findByLabelText(/Rate Scheme/)).toBeInTheDocument();
  });

  it('does not show a flat_fee_price input when a flat-fee service is selected', async () => {
    const { findByLabelText, queryByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '2' } });
    // No flat fee price input should appear
    expect(queryByLabelText(/[Ff]lat fee/)).not.toBeInTheDocument();
  });

  it('saves flat-fee task with active_modifiers as a list (not a dict)', async () => {
    const onSaved = vi.fn();
    const { findByLabelText, getByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, onSaved },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Fix It' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      name: 'Fix It',
      active_modifiers: expect.any(Array),
    }));
    const call = api.post.mock.calls[0];
    expect(Array.isArray(call[1].active_modifiers)).toBe(true);
  });

  it('saves a manual task to /api/jobs/{id}/tasks/', async () => {
    const onSaved = vi.fn();
    const { findByLabelText, getByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, onSaved },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Cut' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    // HOURLY_SCHEME is hour-unit; left untouched, both derived fields go null.
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      name: 'Cut', rate_scheme: 1, est_qty: null, est_worker_time: null,
    }));
    expect(onSaved).toHaveBeenCalled();
  });

  it('saves a manual task on the shop\'s common Hourly scheme with one duration input', async () => {
    const onSaved = vi.fn();
    const { findByLabelText, getByLabelText, getByRole, queryByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, onSaved },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Cut' } });
    // No separate "Estimated qty" input for this (hour-unit) scheme.
    expect(queryByLabelText(/Estimated qty/)).not.toBeInTheDocument();
    await fireEvent.input(getByLabelText(/Estimated hours/), { target: { value: '2:15' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      name: 'Cut', rate_scheme: 1, est_qty: 2.25, est_worker_time: 'PT2H15M',
    }));
    expect(onSaved).toHaveBeenCalled();
  });

  it('renders a field validation error under the offending input on save', async () => {
    api.post.mockRejectedValue({ status: 400, data: { est_qty: ['A valid number is required.'] } });
    const { findByLabelText, getByLabelText, getByRole, findByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Cut' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText('A valid number is required.')).toBeInTheDocument();
  });

  it('renders an operation error in the form footer on save', async () => {
    api.post.mockRejectedValue({ status: 400, data: { detail: 'Job is closed.' } });
    const { findByLabelText, getByLabelText, getByRole, findByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Cut' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const msg = await findByText('Job is closed.');
    expect(msg.closest('[role="alert"]')).not.toBeNull();
  });
  // Task descriptions carry the per-job work specifics, so they need line
  // breaks — the same shape as Job Description in JobEditModal.
  it('renders Description as a textarea that round-trips a multi-line value', async () => {
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    const field = await findByLabelText(/Description/);
    expect(field.tagName).toBe('TEXTAREA');

    const multiline = 'First pass: rough cut\nSecond pass: finish to 0.5mm';
    await fireEvent.input(field, { target: { value: multiline } });
    expect(field.value).toBe(multiline);
  });

  it('POSTs the description with its line breaks intact', async () => {
    const { findByLabelText, getByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Polish' } });
    await fireEvent.input(getByLabelText(/Description/),
      { target: { value: 'line one\nline two' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const taskCall = api.post.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/');
    expect(taskCall[1].description).toBe('line one\nline two');
  });

  it('shows one Estimated hours input for an hour-unit scheme and submits both fields', async () => {
    mockGet({ schemes: [HOUR_UNIT_SCHEME] });
    const onSaved = vi.fn();
    const { findByLabelText, getByLabelText, getByRole, queryByLabelText, queryByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, onSaved },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '7' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Route Panel' } });
    await fireEvent.input(await findByLabelText(/Estimated hours/), { target: { value: '1:30' } });
    // No separate "Estimated qty" spinbutton for hour-unit schemes.
    expect(queryByLabelText(/Estimated qty/)).not.toBeInTheDocument();
    expect(queryByRole('spinbutton')).not.toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      est_qty: 1.5, est_worker_time: 'PT1H30M',
    }));
    expect(onSaved).toHaveBeenCalled();
  });

  it('keeps two inputs for a non-hour scheme', async () => {
    mockGet({ schemes: [EACH_SCHEME] });
    const onSaved = vi.fn();
    const { findByLabelText, getByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, onSaved },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '8' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Widget Batch' } });
    expect(getByLabelText(/Estimated qty/)).toBeInTheDocument();
    expect(getByLabelText(/Estimated worker time/)).toBeInTheDocument();
    await fireEvent.input(getByLabelText(/Estimated qty/), { target: { value: '3' } });
    await fireEvent.input(getByLabelText(/Estimated worker time/), { target: { value: '2:00' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      est_qty: 3, est_worker_time: 'PT2H0M',
    }));
    expect(onSaved).toHaveBeenCalled();
  });
});

const SERVICE_WITH_MODIFIER = {
  rate_scheme_id: 1,
  name: 'CNC Cutting',
  algorithm: 'ELAPSED_TIME',
  rate: '90.00',
  unit_label: 'hr',
  modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
};

describe('WorkItemForm with a pre-selected rateScheme', () => {
  it('shows the chosen service as a header and hides the internal service selector', async () => {
    render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, rateScheme: SERVICE_WITH_MODIFIER },
    });
    // The chosen service name should appear as a read-only header
    expect(await screen.findByText(/CNC Cutting/)).toBeInTheDocument();
    // The internal rate-scheme <select> (labelled "Rate Scheme *") should not be rendered
    expect(screen.queryByLabelText(/Rate Scheme/)).not.toBeInTheDocument();
  });

  it('renders the pre-selected service modifier choices', async () => {
    render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, rateScheme: SERVICE_WITH_MODIFIER },
    });
    // The modifier label should be visible
    expect(await screen.findByText(/Rush/)).toBeInTheDocument();
  });
});

// Task-owned money (Phase 1): the preset dropdown prefills from the shop's
// configured default (/api/settings/ default_rate_scheme), but only when
// that id is actually present in the fetched task-applicable list — a
// default naming a percentage/retired scheme must not preselect a value the
// dropdown doesn't offer.
describe('WorkItemForm preset dropdown default', () => {
  it('preselects the configured default when it is in the task-applicable list', async () => {
    mockGet({ schemes: [HOURLY_SCHEME, FLAT_FEE_SCHEME], defaultRateScheme: '1' });
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    const select = await findByLabelText(/Rate Scheme/);
    await waitFor(() => expect(select.value).toBe('1'));
  });

  it('leaves the dropdown unselected when the default is absent from the list', async () => {
    mockGet({ schemes: [HOURLY_SCHEME], defaultRateScheme: '999' });
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    const select = await findByLabelText(/Rate Scheme/);
    expect(select.value).toBe('');
  });

  it('leaves the dropdown unselected when no default is configured', async () => {
    mockGet({ schemes: [HOURLY_SCHEME], defaultRateScheme: '' });
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    const select = await findByLabelText(/Rate Scheme/);
    expect(select.value).toBe('');
  });
});

// Task-owned money (Phase 1): picking a preset previews its Accounting
// Category alongside rate/unit (create-time only — the server always stamps
// these from the chosen preset; overriding them has no effect until the
// task exists, so the create-time preview is informational, not editable).
describe('WorkItemForm create-time preset preview', () => {
  it('shows the Accounting Category stamped by the selected preset', async () => {
    const { findByLabelText, findByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, categories: CATEGORIES },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    expect(await findByText(/LABOR — Labor/)).toBeInTheDocument();
  });
});

// Task-owned money (Phase 1): create-time active_modifiers is gated on
// MONEY_FIELDS (CanManageJobOrPM/financials) — a worker's checkbox picks
// must never even be POSTed (the key's mere presence 403s), so they ride
// the stamp (zero modifiers) instead.
describe('WorkItemForm modifier checkboxes and money-field gating (manual create)', () => {
  const MOD_SCHEME = {
    rate_scheme_id: 9, name: 'CNC Cutting', algorithm: 'entered_qty',
    rate: '90.00', unit_label: 'ea', modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
    accounting_category: 3,
  };

  it('a manager can check a modifier and it is submitted as a key list', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByLabelText, getByRole, getByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, canManage: true },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '9' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Route it' } });
    const checkbox = getByText(/Rush/).closest('label').querySelector('input[type="checkbox"]');
    expect(checkbox).not.toBeDisabled();
    await fireEvent.click(checkbox);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      active_modifiers: ['rush'],
    }));
  });

  it('a worker sees disabled modifier checkboxes and the create payload omits active_modifiers entirely', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByLabelText, getByRole, getByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, canManage: false },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '9' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Route it' } });
    const checkbox = getByText(/Rush/).closest('label').querySelector('input[type="checkbox"]');
    expect(checkbox).toBeDisabled();
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const call = api.post.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/');
    expect('active_modifiers' in call[1]).toBe(false);
  });
});

// Task-owned money (Phase 1) edit surface: rate_scheme is a create-only
// stamping trigger (never re-forwarded on PATCH — apps/api/mixins.py pops
// it), so editing shows the task's own stamped rate/unit/accounting
// category directly instead of a re-pick dropdown, editable only when the
// caller says this user can manage money for the task's job (item.can_manage
// when present, else the canManage prop).
describe('WorkItemForm editing an existing task\'s money fields', () => {
  const STAMPED_ITEM = {
    task_id: 42, name: 'Mill panel', active_modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
    est_qty: '3', est_worker_time: null,
    rate: '12.50', unit_label: 'ea', accounting_category: 3,
    source_scheme: 9, source_scheme_name: 'CNC Cutting', can_manage: true,
  };
  const MOD_SCHEME = {
    rate_scheme_id: 9, name: 'CNC Cutting', algorithm: 'entered_qty',
    rate: '12.50', unit_label: 'ea', modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
  };

  it('shows the provenance line from source_scheme_name, not a re-pick dropdown', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByText, queryByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true, item: STAMPED_ITEM },
    });
    expect(await findByText(/CNC Cutting/)).toBeInTheDocument();
    expect(queryByLabelText(/Rate Scheme/)).not.toBeInTheDocument();
  });

  it('a manager (item.can_manage) gets editable rate/unit/category inputs prefilled from the task, and PATCHes snapshot-dict modifiers', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByRole, getByText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    const rateInput = await findByLabelText(/^Rate/);
    expect(rateInput).toHaveValue(12.5);
    expect(rateInput).not.toBeDisabled();
    await fireEvent.input(rateInput, { target: { value: '15' } });
    const checkbox = getByText(/Rush/).closest('label').querySelector('input[type="checkbox"]');
    expect(checkbox.checked).toBe(true);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/tasks/42/', expect.objectContaining({
      rate: 15,
      unit_label: 'ea',
      accounting_category: 3,
      active_modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
    }));
  });

  it('a non-manager (item.can_manage=false) sees read-only rate/unit/category and the PATCH omits every money field', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const worker_item = { ...STAMPED_ITEM, can_manage: false };
    const { findByText, queryByLabelText, getByRole } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: worker_item, categories: CATEGORIES,
      },
    });
    await findByText(/CNC Cutting/);
    expect(queryByLabelText(/^Rate/)).not.toBeInTheDocument();
    // Existing modifier still visible, just not interactive.
    expect(await findByText(/Rush/)).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const call = api.patch.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/42/');
    for (const f of ['rate', 'unit_label', 'accounting_category', 'active_modifiers']) {
      expect(f in call[1]).toBe(false);
    }
  });
});
