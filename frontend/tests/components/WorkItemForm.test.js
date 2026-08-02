import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Error',
}));

import { api } from '@/lib/api.js';
import WorkItemForm from '@/components/WorkItemForm.svelte';

const HOURLY_SCHEME = { rate_scheme_id: 1, name: 'Hourly', algorithm: 'elapsed_time', rate: '25', unit_label: 'hr', modifiers: [] };
const FLAT_FEE_SCHEME = { rate_scheme_id: 2, name: 'Quick Fix', algorithm: 'flat_fee', rate: '150', unit_label: 'none', modifiers: [] };
const HOUR_UNIT_SCHEME = { rate_scheme_id: 7, name: 'CNC Hourly', algorithm: 'elapsed_time', rate: '90', unit_label: 'hour', modifiers: [] };
const EACH_SCHEME = { rate_scheme_id: 8, name: 'Widget', algorithm: 'entered_qty', rate: '10', unit_label: 'ea', modifiers: [] };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ results: [HOURLY_SCHEME, FLAT_FEE_SCHEME] });
  api.post.mockResolvedValue({});
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
    const { queryByLabelText } = render(WorkItemForm, {
      props: { open: true, mode: 'manual', context: 'job', contextId: 5, isEdit: true,
        item: { name: 'X', rate_scheme: 1, active_modifiers: [], est_qty: '1' } },
    });
    expect(queryByLabelText(/save to catalog/i)).not.toBeInTheDocument();
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

    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/tasks/', expect.objectContaining({
      name: 'Cut', rate_scheme: 1, est_worker_time: null,
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
    api.get.mockResolvedValue({ results: [HOUR_UNIT_SCHEME] });
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
    api.get.mockResolvedValue({ results: [EACH_SCHEME] });
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
