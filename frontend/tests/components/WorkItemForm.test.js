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
const UNITS = ['none', 'ea', 'hour', 'min', 'sheet', 'sq ft', 'ft', 'yd', 'm'];

// Routes api.get by URL prefix. The default preset comes from the
// `is_default` flag on the rate-scheme list itself (RM browser-testing
// note 3) — the form no longer reads /api/settings/ at all, so no route
// for it here; a stray call would just fall through to the catch-all.
// /api/settings/units/ is a separate (IsAuthenticated) endpoint — the edit-
// mode Unit field's UnitsSelect (RM browser-testing note 4) hits it.
function mockGet({ schemes = [HOURLY_SCHEME, FLAT_FEE_SCHEME] } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: schemes });
    if (url.startsWith('/api/settings/units/')) return Promise.resolve(UNITS);
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

// Task-owned money (Phase 1); RM browser-testing note 3 (frontend half): the
// preset dropdown prefills from the `is_default` flag embedded on the
// already-fetched task-applicable list — never from /api/settings/, which
// is CanManageConfig-gated and 403s silently for a permissionless worker.
describe('WorkItemForm preset dropdown default', () => {
  it('preselects the row flagged is_default in the task-applicable list', async () => {
    mockGet({ schemes: [{ ...HOURLY_SCHEME, is_default: true }, FLAT_FEE_SCHEME] });
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    const select = await findByLabelText(/Rate Scheme/);
    await waitFor(() => expect(select.value).toBe('1'));
  });

  it('leaves the dropdown unselected when no row is flagged is_default', async () => {
    mockGet({ schemes: [HOURLY_SCHEME, FLAT_FEE_SCHEME] });
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    const select = await findByLabelText(/Rate Scheme/);
    expect(select.value).toBe('');
  });

  it('preselects the default for a permissionless user without ever calling /api/settings/', async () => {
    // The exact scenario RM hit: a worker with no permission atoms (canManage
    // false is the default prop) opens the create-task form. Preselection
    // must work off the rate-scheme list alone.
    mockGet({ schemes: [{ ...HOURLY_SCHEME, is_default: true }, FLAT_FEE_SCHEME] });
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, canManage: false },
    });
    const select = await findByLabelText(/Rate Scheme/);
    await waitFor(() => expect(select.value).toBe('1'));
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/api/settings/'));
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

// task-owned-money Phase 3, Task 2: a manager may override the stamped
// accounting_category at create time (including clearing it to null,
// "categorize at invoicing"); a non-manager (default canManage prop) still
// only gets the read-only preview and never sends the key.
describe('WorkItemForm create-time accounting_category override (manager only)', () => {
  it('defaults the select to the preset AC and submits it unless changed', async () => {
    const { findByLabelText, getByRole } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5,
        categories: CATEGORIES, canManage: true,
      },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(await findByLabelText(/Name/), { target: { value: 'Route it' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      accounting_category: 3,
    }));
  });

  it('a manager can clear the AC to null via the "none" option', async () => {
    const { findByLabelText, getByRole, getByLabelText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5,
        categories: CATEGORIES, canManage: true,
      },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(await findByLabelText(/Name/), { target: { value: 'Flat task' } });
    await fireEvent.change(getByLabelText(/Accounting Category/), { target: { value: '' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      accounting_category: null,
    }));
  });

  it('a non-manager gets the read-only preview and never sends accounting_category', async () => {
    const { findByLabelText, getByRole, queryByLabelText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5,
        categories: CATEGORIES, canManage: false,
      },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '1' } });
    await fireEvent.input(await findByLabelText(/Name/), { target: { value: 'Worker task' } });
    expect(queryByLabelText(/Accounting Category/)).not.toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const call = api.post.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/');
    expect('accounting_category' in call[1]).toBe(false);
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

// Task 12b: `active_modifiers` on add-from-template is money-equivalent to
// MONEY_FIELDS on the direct-create/PATCH endpoints — the backend now 403s a
// non-manager who sends the key at all (even []), so the checkboxes must be
// disabled for a non-manager and the payload must omit the key entirely,
// matching the manual-create gating above exactly.
describe('WorkItemForm modifier checkboxes and money-field gating (template create)', () => {
  const MOD_SCHEME = {
    rate_scheme_id: 9, name: 'CNC Cutting', algorithm: 'entered_qty',
    rate: '90.00', unit_label: 'ea', modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
    accounting_category: 3,
  };
  const TEMPLATE_WITH_MOD_SCHEME = {
    template_id: 20, template_name: 'Router Pass', rate_scheme: 9,
    default_active_modifiers: [],
  };

  it('a manager can check a modifier and it is submitted as a key list', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByRole, getByText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'template', context: 'job', contextId: 5,
        templates: [TEMPLATE_WITH_MOD_SCHEME], presetTemplateId: 20, canManage: true,
      },
    });
    await findByLabelText(/template/i);
    const checkbox = await waitFor(() => {
      const el = getByText(/Rush/).closest('label').querySelector('input[type="checkbox"]');
      expect(el).not.toBeDisabled();
      return el;
    });
    await fireEvent.click(checkbox);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/add-from-template/', expect.objectContaining({
      active_modifiers: ['rush'],
    }));
  });

  it('a worker sees disabled modifier checkboxes and the payload omits active_modifiers entirely', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByRole, getByText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'template', context: 'job', contextId: 5,
        templates: [TEMPLATE_WITH_MOD_SCHEME], presetTemplateId: 20, canManage: false,
      },
    });
    await findByLabelText(/template/i);
    await waitFor(() => {
      const checkbox = getByText(/Rush/).closest('label').querySelector('input[type="checkbox"]');
      expect(checkbox).toBeDisabled();
    });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const call = api.post.mock.calls.find((c) => c[0] === '/api/jobs/5/add-from-template/');
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
    // RM browser-testing note 4: the Unit field next to Rate is the standard
    // UnitsSelect dropdown, not a stray text input — same "Unit" label,
    // prefilled from the task's own stamped unit_label.
    const unitSelect = await findByLabelText(/^Unit/);
    expect(unitSelect.tagName).toBe('SELECT');
    expect(unitSelect).toHaveValue('ea');
    expect(unitSelect).not.toBeDisabled();
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

  it('changing the Unit dropdown round-trips the new value to the PATCH payload', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByRole } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    const unitSelect = await findByLabelText(/^Unit/);
    // UnitsSelect loads its option list from /api/settings/units/ async —
    // wait for the target option to actually be selectable before firing
    // change (a native select ignores a change to a not-yet-rendered value).
    await waitFor(() => expect(unitSelect.querySelector('option[value="hour"]')).toBeInTheDocument());
    await fireEvent.change(unitSelect, { target: { value: 'hour' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/tasks/42/', expect.objectContaining({
      unit_label: 'hour',
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
    // Unit dropdown is likewise absent for a non-manager — the read-only
    // "$rate/unit" text line stands in for it instead.
    expect(queryByLabelText(/^Unit/)).not.toBeInTheDocument();
    expect(await findByText(/\$12\.50\/ea/)).toBeInTheDocument();
    // Existing modifier still visible, just not interactive.
    expect(await findByText(/Rush/)).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const call = api.patch.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/42/');
    for (const f of ['rate', 'unit_label', 'accounting_category', 'active_modifiers']) {
      expect(f in call[1]).toBe(false);
    }
  });

  // task-owned-money Phase 3, Task 2: accounting_category is optional
  // end-to-end — a manager may clear it to null via the select's explicit
  // "none" option.
  it('offers an explicit "none" option and PATCHes null when the manager picks it', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByRole, getByLabelText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    await findByLabelText(/^Rate/);
    const select = getByLabelText(/Accounting Category/);
    expect(select.querySelector('option[value=""]').textContent).toMatch(
      /none \(categorize at invoicing\)/i,
    );
    await fireEvent.change(select, { target: { value: '' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/tasks/42/', expect.objectContaining({
      accounting_category: null,
    }));
  });
});

// Quantity structure (spec §9, task-owned-money Phase 4 Task 4): the
// qty_scales_with_parent checkbox + its ALWAYS-visible inline derived
// expectation line render ONLY on subtask forms (create-subtask context, or
// editing an existing subtask), defaulted unit-keyed from the PARENT's own
// unit_label ('ea' -> checked) — mirroring TaskService.create_direct's
// server-side default (apps/jobs/services.py) so the checkbox's initial
// state is never a lie about what the server would pick.
describe('WorkItemForm subtask mode — qty_scales_with_parent', () => {
  const PARENT_EA = { task_id: 50, name: 'Widget batch', unit_label: 'ea', est_qty: '10' };
  const PARENT_HR = { task_id: 51, name: 'Sanding job', unit_label: 'hour', est_qty: '4' };
  const PARENT_NO_QTY = { task_id: 52, name: 'Custom order', unit_label: 'ea', est_qty: null };

  function mockGetWithParent(parent, schemes = [EACH_SCHEME]) {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: schemes });
      if (url === `/api/tasks/${parent.task_id}/`) return Promise.resolve(parent);
      return Promise.resolve({});
    });
  }

  it('shows no qty_scales_with_parent checkbox in job (non-subtask) context', async () => {
    const { findByLabelText, queryByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5 },
    });
    await findByLabelText(/Rate Scheme/);
    expect(queryByLabelText(/scales with parent/i)).not.toBeInTheDocument();
  });

  it('defaults the checkbox CHECKED when the parent unit is "ea"', async () => {
    mockGetWithParent(PARENT_EA);
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'subtask', contextId: PARENT_EA.task_id },
    });
    const checkbox = await findByLabelText(/scales with parent/i);
    await waitFor(() => expect(checkbox.checked).toBe(true));
  });

  it('defaults the checkbox UNCHECKED when the parent unit is not "ea"', async () => {
    mockGetWithParent(PARENT_HR, [HOUR_UNIT_SCHEME]);
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'subtask', contextId: PARENT_HR.task_id },
    });
    const checkbox = await findByLabelText(/scales with parent/i);
    await waitFor(() => expect(checkbox.checked).toBe(false));
  });

  it('sends qty_scales_with_parent on subtask create, freely overridable', async () => {
    mockGetWithParent(PARENT_EA);
    const { findByLabelText, getByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'subtask', contextId: PARENT_EA.task_id },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '8' } });
    await fireEvent.input(getByLabelText(/Name/), { target: { value: 'Per-widget polish' } });
    const checkbox = await findByLabelText(/scales with parent/i);
    await waitFor(() => expect(checkbox.checked).toBe(true));
    await fireEvent.click(checkbox); // uncheck it — freely overridable
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith(`/api/tasks/${PARENT_EA.task_id}/subtasks/`, expect.objectContaining({
      qty_scales_with_parent: false,
    }));
  });

  it('shows the derived expectation line multiplying per-unit qty by the parent quantity', async () => {
    mockGetWithParent(PARENT_EA);
    const { findByLabelText, getByLabelText, findByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'subtask', contextId: PARENT_EA.task_id },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '8' } });
    await fireEvent.input(getByLabelText(/Estimated qty/), { target: { value: '2' } });
    // 2 ea/unit x 10 (parent est_qty) = 20 expected
    expect(await findByText(/20 expected/)).toBeInTheDocument();
  });

  it('a flag-false (batch) subtask does not multiply — expected equals the raw qty', async () => {
    mockGetWithParent(PARENT_EA);
    const { findByLabelText, getByLabelText, findByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'subtask', contextId: PARENT_EA.task_id },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '8' } });
    const checkbox = await findByLabelText(/scales with parent/i);
    await waitFor(() => expect(checkbox.checked).toBe(true));
    await fireEvent.click(checkbox); // batch total, not per-unit
    await fireEvent.input(getByLabelText(/Estimated qty/), { target: { value: '7' } });
    expect(await findByText(/7 ea per batch/)).toBeInTheDocument();
  });

  it('shows an explicit "parent quantity not set" state instead of a silently-computed number', async () => {
    // Reviewer flag carried from Task 1 (progress.md): a flag-true subtask
    // whose parent has no est_qty must NEVER render a silent x1 total.
    mockGetWithParent(PARENT_NO_QTY);
    const { findByLabelText, getByLabelText, findByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'subtask', contextId: PARENT_NO_QTY.task_id },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '8' } });
    await fireEvent.input(getByLabelText(/Estimated qty/), { target: { value: '2' } });
    expect(await findByText(/parent quantity not set/i)).toBeInTheDocument();
  });

  it('offers the checkbox and PATCHes it when editing an existing subtask', async () => {
    mockGetWithParent(PARENT_EA);
    const subtaskItem = {
      task_id: 60, name: 'Per-unit sand', parent_task: PARENT_EA.task_id,
      active_modifiers: [], est_qty: '1', est_worker_time: null,
      rate: '5', unit_label: 'ea', qty_scales_with_parent: false, can_manage: true,
    };
    const { findByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true, item: subtaskItem },
    });
    const checkbox = await findByLabelText(/scales with parent/i);
    expect(checkbox.checked).toBe(false);
    await fireEvent.click(checkbox);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/tasks/60/', expect.objectContaining({
      qty_scales_with_parent: true,
    }));
  });

  it('omits qty_scales_with_parent when editing a top-level (non-subtask) task', async () => {
    const item = {
      task_id: 61, name: 'Flat task', parent_task: null, active_modifiers: [],
      est_qty: '1', est_worker_time: null, can_manage: true,
    };
    const { findByLabelText, getByRole } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true, item },
    });
    await findByLabelText(/Name/);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    const call = api.patch.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/61/');
    expect('qty_scales_with_parent' in call[1]).toBe(false);
  });
});

// Drift tripwire (reviewer finding): expectedPreview re-implements
// Task._parent_multiplier() (apps/jobs/models.py) client-side for an
// unsaved-input preview — the same established pattern as
// RateSchemeManager.svelte's previewTotal (re-implements Task.
// effective_rate() the same way, since task-owned-money Phase 1). Anchor
// the preview against the BACKEND's own recorded numbers for these exact
// inputs — tests/test_quantity_structure.py's
// test_flag_true_multiplies_by_parent_qty (parent est_qty=500, child
// est_qty=20 -> expected_qty=10000) and the API-layer assertion that
// TaskSerializer actually renders that as expected_qty: '10000.00'. If
// `_parent_multiplier()`'s math ever changes (rounding, clamping, a
// different fallback), this is the test that goes red first.
describe('WorkItemForm subtask preview matches the backend\'s own expected_qty (drift tripwire)', () => {
  const PARENT_BATCH = { task_id: 70, name: 'Batch of boards', unit_label: 'ea', est_qty: '500' };
  // apps/jobs/models.py Task._parent_multiplier()/expected_qty() for these
  // exact inputs, as TaskSerializer.get_expected_qty() actually renders it.
  const API_EXPECTED_QTY = '10000.00';

  it('the live preview equals the API-provided expected_qty for the same parent/child inputs', async () => {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/rate-schemes/')) return Promise.resolve({ results: [EACH_SCHEME] });
      if (url === `/api/tasks/${PARENT_BATCH.task_id}/`) return Promise.resolve(PARENT_BATCH);
      return Promise.resolve({});
    });
    const { findByLabelText, getByLabelText, findByText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'subtask', contextId: PARENT_BATCH.task_id },
    });
    await fireEvent.change(await findByLabelText(/Rate Scheme/), { target: { value: '8' } });
    await fireEvent.input(getByLabelText(/Estimated qty/), { target: { value: '20' } });
    expect(await findByText(
      new RegExp(`${Number(API_EXPECTED_QTY)} expected`)
    )).toBeInTheDocument();
  });
});
