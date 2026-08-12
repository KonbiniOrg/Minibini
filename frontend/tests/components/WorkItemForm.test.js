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
        item: { name: 'X', active_modifiers: [], est_qty: '1', rate: '25', unit_label: 'hour', can_manage: true, can_write_money: true } },
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
// caller says this user may write money for the task's job (item.can_write_money
// when present, else the canManage prop). RM browser-testing note 6:
// gating moved from item.can_manage to item.can_write_money — a dedicated
// SerializerMethodField mirroring TaskSerializer._can_write_money() —
// because can_manage (can_manage_jobs atom or PM) under-covers a
// financials-only caller, who the server's own write-gate DOES accept.
describe('WorkItemForm editing an existing task\'s money fields', () => {
  const STAMPED_ITEM = {
    task_id: 42, name: 'Mill panel', active_modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
    est_qty: '3', est_worker_time: null,
    rate: '12.50', unit_label: 'ea', accounting_category: 3,
    source_scheme: 9, source_scheme_name: 'CNC Cutting', can_manage: true, can_write_money: true,
  };
  const MOD_SCHEME = {
    rate_scheme_id: 9, name: 'CNC Cutting', algorithm: 'entered_qty',
    // Deliberately drifted from STAMPED_ITEM's own rate/unit_label/AC
    // (99.00 vs 12.50, ea vs ea-but-different-AC) — a Rate Scheme's list
    // data can legitimately move after a task stamped from it (task-owned
    // money Phase 1: stamping is a one-time copy). Using drifted values here
    // makes it possible to positively assert "no restamp happened" (same-
    // select no-op) vs. "restamp did happen" (genuine change) rather than
    // the two cases coincidentally producing identical numbers.
    rate: '99.00', unit_label: 'ea', accounting_category: 3,
    modifiers: [{ key: 'rush', label: 'Rush', percent: 15 }],
  };
  const OTHER_SCHEME = {
    rate_scheme_id: 10, name: 'Laser Cutting', algorithm: 'entered_qty',
    rate: '20.00', unit_label: 'hour', accounting_category: 4,
    modifiers: [{ key: 'expedite', label: 'Expedite', percent: 8 }],
  };

  it('a manager sees the Rate Scheme dropdown preselected to the current scheme', async () => {
    mockGet({ schemes: [MOD_SCHEME, OTHER_SCHEME] });
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true, item: STAMPED_ITEM },
    });
    const select = await findByLabelText(/Rate Scheme/);
    expect(select.tagName).toBe('SELECT');
    expect(select).toHaveValue('9');
    expect(select).not.toBeDisabled();
  });

  it('a non-manager still sees the read-only provenance line, no dropdown', async () => {
    mockGet({ schemes: [MOD_SCHEME, OTHER_SCHEME] });
    const worker_item = { ...STAMPED_ITEM, can_manage: false, can_write_money: false };
    const { findByText, queryByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true, item: worker_item },
    });
    expect(await findByText(/CNC Cutting/)).toBeInTheDocument();
    expect(queryByLabelText(/Rate Scheme/)).not.toBeInTheDocument();
  });

  it('a retired current scheme (absent from the task-applicable list) renders as a disabled "(retired)" option', async () => {
    // MOD_SCHEME (id 9, the task's current source_scheme) is NOT in the
    // fetched list — simulating retirement (task_applicable=true excludes
    // inactive presets server-side).
    mockGet({ schemes: [OTHER_SCHEME] });
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true, item: STAMPED_ITEM },
    });
    const select = await findByLabelText(/Rate Scheme/);
    expect(select).toHaveValue('9');
    const opt = select.querySelector('option[value="9"]');
    expect(opt).not.toBeNull();
    expect(opt.disabled).toBe(true);
    expect(opt.textContent).toMatch(/CNC Cutting/);
    expect(opt.textContent).toMatch(/retired/i);
  });

  it('a null source_scheme renders as a disabled "—" placeholder option', async () => {
    mockGet({ schemes: [MOD_SCHEME, OTHER_SCHEME] });
    const null_item = { ...STAMPED_ITEM, source_scheme: null, source_scheme_name: null };
    const { findByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true, item: null_item },
    });
    const select = await findByLabelText(/Rate Scheme/);
    expect(select).toHaveValue('');
    const opt = select.querySelector('option[value=""]');
    expect(opt).not.toBeNull();
    expect(opt.disabled).toBe(true);
  });

  it('changing the Rate Scheme dropdown restamps rate/unit/category and swaps modifier definitions to none-checked', async () => {
    mockGet({ schemes: [MOD_SCHEME, OTHER_SCHEME] });
    const { findByLabelText, getByLabelText, getByText, queryByText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    const schemeSelect = await findByLabelText(/Rate Scheme/);
    await fireEvent.change(schemeSelect, { target: { value: '10' } });
    expect(await findByLabelText(/^Rate$/)).toHaveValue(20);
    expect(getByLabelText(/^Unit/)).toHaveValue('hour');
    expect(getByLabelText(/Accounting Category/)).toHaveValue('4');
    // Old scheme's modifier ("Rush") is gone; new scheme's ("Expedite") is
    // present and unchecked — the set replaced wholesale, none checked.
    expect(queryByText(/Rush/)).not.toBeInTheDocument();
    const expediteCheckbox = getByText(/Expedite/).closest('label').querySelector('input[type="checkbox"]');
    expect(expediteCheckbox.checked).toBe(false);
  });

  it('A -> B -> A ends with A\'s fresh list values, not the task\'s original stamped values', async () => {
    mockGet({ schemes: [MOD_SCHEME, OTHER_SCHEME] });
    const { findByLabelText, getByLabelText, getByText, queryByText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    const schemeSelect = await findByLabelText(/Rate Scheme/);
    await fireEvent.change(schemeSelect, { target: { value: '10' } }); // A -> B
    await fireEvent.change(schemeSelect, { target: { value: '9' } });  // B -> A
    // A's CURRENT list rate (99.00), not the task's original stamped rate
    // (12.50) — a fresh pick of A means A's current data.
    expect(await findByLabelText(/^Rate$/)).toHaveValue(99);
    expect(getByLabelText(/^Unit/)).toHaveValue('ea');
    expect(getByLabelText(/Accounting Category/)).toHaveValue('3');
    expect(queryByText(/Expedite/)).not.toBeInTheDocument();
    const rushCheckbox = getByText(/Rush/).closest('label').querySelector('input[type="checkbox"]');
    expect(rushCheckbox.checked).toBe(false); // restamped, not carried over checked
  });

  it('re-selecting the current scheme is a no-op — no restamp, task\'s original values stand', async () => {
    mockGet({ schemes: [MOD_SCHEME, OTHER_SCHEME] });
    const { findByLabelText, getByLabelText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    const schemeSelect = await findByLabelText(/Rate Scheme/);
    await fireEvent.change(schemeSelect, { target: { value: '9' } }); // same as current
    // Task's own stamped rate (12.50), NOT MOD_SCHEME's drifted list rate
    // (99.00) — proves no restamp fired.
    expect(getByLabelText(/^Rate$/)).toHaveValue(12.5);
    expect(getByLabelText(/^Unit/)).toHaveValue('ea');
    expect(getByLabelText(/Accounting Category/)).toHaveValue('3');
  });

  it('the PATCH payload includes source_scheme only when it actually changed', async () => {
    mockGet({ schemes: [MOD_SCHEME, OTHER_SCHEME] });
    const { findByLabelText, getByRole } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    await findByLabelText(/Rate Scheme/);
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    let call = api.patch.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/42/');
    expect('source_scheme' in call[1]).toBe(false);

    api.patch.mockClear();
    const schemeSelect = await findByLabelText(/Rate Scheme/);
    await fireEvent.change(schemeSelect, { target: { value: '10' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    call = api.patch.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/42/');
    expect(call[1].source_scheme).toBe(10);
  });

  it('a manager (item.can_manage) gets editable rate/unit/category inputs prefilled from the task, and PATCHes snapshot-dict modifiers', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByRole, getByText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    const rateInput = await findByLabelText(/^Rate$/);
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

  // Phase 3 Task 4: a task's own accounting_category is now nullable —
  // "categorize at invoicing" instead of forcing a pick.
  describe('nullable accounting_category (Phase 3)', () => {
    it('the category select offers an explicit "none" option labeled exactly "— none (categorize at invoicing) —"', async () => {
      mockGet({ schemes: [MOD_SCHEME] });
      const { findByLabelText } = render(WorkItemForm, {
        props: {
          open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
          item: STAMPED_ITEM, categories: CATEGORIES,
        },
      });
      const select = await findByLabelText(/Accounting Category/);
      const noneOption = select.querySelector('option[value=""]');
      expect(noneOption).not.toBeNull();
      expect(noneOption.textContent).toBe('— none (categorize at invoicing) —');
    });

    it('a task with a null accounting_category opens with the "none" option selected', async () => {
      mockGet({ schemes: [MOD_SCHEME] });
      const nullAcItem = { ...STAMPED_ITEM, accounting_category: null };
      const { findByLabelText } = render(WorkItemForm, {
        props: {
          open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
          item: nullAcItem, categories: CATEGORIES,
        },
      });
      const select = await findByLabelText(/Accounting Category/);
      expect(select).toHaveValue('');
    });

    it('picking "none" and saving PATCHes accounting_category as null, not an empty string', async () => {
      mockGet({ schemes: [MOD_SCHEME] });
      const { findByLabelText, getByRole } = render(WorkItemForm, {
        props: {
          open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
          item: STAMPED_ITEM, categories: CATEGORIES,
        },
      });
      const select = await findByLabelText(/Accounting Category/);
      expect(select).toHaveValue('3'); // starts on the task's stamped category
      await fireEvent.change(select, { target: { value: '' } });
      await fireEvent.click(getByRole('button', { name: 'Save' }));
      const call = api.patch.mock.calls.find((c) => c[0] === '/api/jobs/5/tasks/42/');
      expect(call[1].accounting_category).toBeNull();
    });

    it('a non-money-writer sees "uncategorized" (not blank) for a null-AC task', async () => {
      mockGet({ schemes: [MOD_SCHEME] });
      const nullAcWorkerItem = {
        ...STAMPED_ITEM, accounting_category: null, can_manage: false, can_write_money: false,
      };
      const { findByText } = render(WorkItemForm, {
        props: {
          open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
          item: nullAcWorkerItem, categories: CATEGORIES,
        },
      });
      expect(await findByText(/uncategorized/)).toBeInTheDocument();
    });
  });

  it('a financials-only caller (item.can_manage=false, item.can_write_money=true) still gets editable, non-greyed rate/unit/category inputs — RM browser-testing note 6', async () => {
    // The exact bug this note fixed: can_manage (can_manage_jobs atom or
    // PM) is false for a financials-only caller, but the server's actual
    // write-gate (TaskSerializer._can_write_money, which can_write_money
    // mirrors) accepts them. The SPA must gate on can_write_money, not
    // can_manage, or this caller sees fields the server would accept
    // rendered disabled/read-only.
    mockGet({ schemes: [MOD_SCHEME] });
    const financialsItem = { ...STAMPED_ITEM, can_manage: false, can_write_money: true };
    const { findByLabelText, getByRole, getByText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: financialsItem, categories: CATEGORIES,
      },
    });
    const rateInput = await findByLabelText(/^Rate$/);
    expect(rateInput).not.toBeDisabled();
    expect(rateInput.className).not.toMatch(/muted|disabled|readonly/i);
    const unitSelect = await findByLabelText(/^Unit/);
    expect(unitSelect).not.toBeDisabled();
    const checkbox = getByText(/Rush/).closest('label').querySelector('input[type="checkbox"]');
    expect(checkbox).not.toBeDisabled();
    await fireEvent.input(rateInput, { target: { value: '20' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/tasks/42/', expect.objectContaining({
      rate: 20,
    }));
  });

  it('lays Rate/per/Unit out as one non-wrapping row (RM note 4 follow-up: dropdown landed but still line-wrapped)', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const { findByLabelText, getByText } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: STAMPED_ITEM, categories: CATEGORIES,
      },
    });
    const rateInput = await findByLabelText(/^Rate$/);
    const unitSelect = await findByLabelText(/^Unit/);
    const row = rateInput.closest('.rate-unit-row');
    expect(row).not.toBeNull();
    expect(row).toContainElement(unitSelect);
    expect(row).toContainElement(getByText('per'));
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

  it('a worker (item.can_write_money=false) sees read-only rate/unit/category and the PATCH omits every money field', async () => {
    mockGet({ schemes: [MOD_SCHEME] });
    const worker_item = { ...STAMPED_ITEM, can_manage: false, can_write_money: false };
    const { findByText, queryByLabelText, getByRole } = render(WorkItemForm, {
      props: {
        open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: worker_item, categories: CATEGORIES,
      },
    });
    await findByText(/CNC Cutting/);
    expect(queryByLabelText(/^Rate$/)).not.toBeInTheDocument();
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
});
