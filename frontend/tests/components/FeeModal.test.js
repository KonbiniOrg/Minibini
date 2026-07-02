import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

import { api } from '@/lib/api.js';
import FeeModal from '@/components/FeeModal.svelte';

const CATEGORIES = [
  { id: 1, code: 'RUSH', name: 'Rush Charges' },
  { id: 2, code: 'MISC', name: 'Miscellaneous' },
];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.delete.mockReset();
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
  api.delete.mockResolvedValue({});
});

describe('FeeModal — create', () => {
  it('posts the correct payload to /api/jobs/{id}/fees/ on save', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(FeeModal, {
      props: { open: true, mode: 'create', jobId: 7, categories: CATEGORIES, onSaved },
    });

    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Rush surcharge' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/Unit Rate/), { target: { value: '50' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/jobs/7/fees/', {
      description: 'Rush surcharge',
      quantity: 2,
      unit_rate: 50,
      accounting_category: null,
      task: null,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('includes accounting_category in the payload when selected', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(FeeModal, {
      props: { open: true, mode: 'create', jobId: 7, categories: CATEGORIES, onSaved },
    });

    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Misc fee' } });
    await fireEvent.change(getByLabelText(/Accounting Category/), { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/jobs/7/fees/', expect.objectContaining({
      accounting_category: 2,
    }));
  });

  it('renders the accounting category select populated from the categories prop', () => {
    const { getByLabelText } = render(FeeModal, {
      props: { open: true, mode: 'create', jobId: 7, categories: CATEGORIES },
    });
    const select = getByLabelText(/Accounting Category/);
    // Two real options plus the "-- None --" placeholder
    expect(select.options.length).toBe(3);
    expect(select.options[1].text).toContain('RUSH');
    expect(select.options[2].text).toContain('MISC');
  });

  it('surfaces a save error when the API call fails', async () => {
    // api.js sets err.message = json.detail when present; mock the same shape.
    api.post.mockRejectedValue({ message: 'Invalid fee.' });
    const { getByLabelText, getByRole, findByText } = render(FeeModal, {
      props: { open: true, mode: 'create', jobId: 7, categories: [] },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Bad fee' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText(/Invalid fee\./)).toBeInTheDocument();
  });

  it('defaults quantity to 1 in create mode', () => {
    const { getByLabelText } = render(FeeModal, {
      props: { open: true, mode: 'create', jobId: 7, categories: [] },
    });
    expect(getByLabelText(/Quantity/).value).toBe('1');
  });

  it('calls onClose when Cancel is clicked', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(FeeModal, {
      props: { open: true, mode: 'create', jobId: 7, categories: [], onClose },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('includes task in the POST payload when taskId prop is provided', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(FeeModal, {
      props: { open: true, mode: 'create', jobId: 7, taskId: 99, categories: [], onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Task fee' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/7/fees/', expect.objectContaining({
      task: 99,
    }));
  });

  it('sends task: null in the POST payload when taskId prop is not provided', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(FeeModal, {
      props: { open: true, mode: 'create', jobId: 7, categories: [], onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Unassigned fee' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/7/fees/', expect.objectContaining({
      task: null,
    }));
  });
});

describe('FeeModal — edit', () => {
  const existingFee = { fee_id: 42, description: 'Setup fee', quantity: '1', unit_rate: '75', accounting_category: null };

  it('pre-populates fields from the fee prop', () => {
    const { getByLabelText } = render(FeeModal, {
      props: { open: true, mode: 'edit', fee: existingFee, jobId: 7, categories: [] },
    });
    expect(getByLabelText(/Description/).value).toBe('Setup fee');
    expect(getByLabelText(/Unit Rate/).value).toBe('75');
  });

  it('patches the fee on save', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(FeeModal, {
      props: { open: true, mode: 'edit', fee: existingFee, jobId: 7, categories: [], onSaved },
    });
    await fireEvent.input(getByLabelText(/Unit Rate/), { target: { value: '100' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/7/fees/42/', expect.objectContaining({
      unit_rate: 100,
    }));
    expect(onSaved).toHaveBeenCalled();
  });

  it('requires a second click to confirm delete', async () => {
    const onSaved = vi.fn();
    const { getByRole } = render(FeeModal, {
      props: { open: true, mode: 'edit', fee: existingFee, jobId: 7, categories: [], onSaved },
    });
    // First click → shows "Confirm delete"
    await fireEvent.click(getByRole('button', { name: 'Delete' }));
    expect(api.delete).not.toHaveBeenCalled();
    // Second click (on Confirm delete) → fires the API call
    await fireEvent.click(getByRole('button', { name: 'Confirm delete' }));
    expect(api.delete).toHaveBeenCalledWith('/api/jobs/7/fees/42/');
    expect(onSaved).toHaveBeenCalled();
  });
});
