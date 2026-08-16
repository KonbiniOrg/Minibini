import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import BundleModal from '@/components/docsurface/BundleModal.svelte';

const SINGLE_ATOM = [
  { type: 'task', id: 41, description: 'Sand edges', qty: '2', units: 'hour', rate: '30.00', amount: '60.00' },
];

const MULTI_ATOMS = [
  { type: 'task', id: 41, description: 'Sand edges', qty: '2', units: 'hour', rate: '30.00', amount: '60.00' },
  { type: 'material', id: 9, description: 'Steel', qty: '3', units: 'none', rate: '5.00', amount: '15.00' },
];

// Three same-rate, same-unit tasks — the client-side mirror of
// BaseWizardService._uniform_money_bundle (apps/core/wizard.py) should
// seed qty=12 (summed), units='hour', price='25.00' (the shared rate).
const UNIFORM_TASK_ATOMS = [
  { type: 'task', id: 1, description: 'Cut A', qty: '4', units: 'hour', rate: '25.00', amount: '100.00' },
  { type: 'task', id: 2, description: 'Cut B', qty: '4', units: 'hour', rate: '25.00', amount: '100.00' },
  { type: 'task', id: 3, description: 'Cut C', qty: '4', units: 'hour', rate: '25.00', amount: '100.00' },
];

// Fractional two-decimal quantities (real time-tracked hours) — plain
// float addition of three 1.10s produces "3.3000000000000003"; the seed
// must round to "3.30" so an un-retouched submit doesn't get rejected by
// the DecimalField(decimal_places=2).
const FRACTIONAL_UNIFORM_TASK_ATOMS = [
  { type: 'task', id: 1, description: 'Cut A', qty: '1.1', units: 'hour', rate: '25.00', amount: '27.50' },
  { type: 'task', id: 2, description: 'Cut B', qty: '1.1', units: 'hour', rate: '25.00', amount: '27.50' },
  { type: 'task', id: 3, description: 'Cut C', qty: '1.1', units: 'hour', rate: '25.00', amount: '27.50' },
];

// Same rate but a differing unit — must NOT be treated as uniform.
const DIFFERING_UNITS_ATOMS = [
  { type: 'task', id: 1, description: 'Cut A', qty: '4', units: 'hour', rate: '25.00', amount: '100.00' },
  { type: 'task', id: 2, description: 'Cut B', qty: '4', units: 'ea', rate: '25.00', amount: '100.00' },
];

function conflictError() {
  return Object.assign(new Error('Some atoms were claimed by another estimate.'), {
    status: 409,
    data: { detail: 'Some atoms were claimed by another estimate.', code: 'atoms_already_claimed' },
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue(['none', 'hour', 'ea']); // UnitsSelect (/api/settings/units/)
  api.post.mockResolvedValue({ line_item_id: 99 });
  clearMessage();
});

function baseProps(overrides = {}) {
  return {
    open: true,
    atoms: SINGLE_ATOM,
    apiBase: '/api/estimates/7',
    onCreated: vi.fn(),
    onConflict: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
}

describe('BundleModal', () => {
  it('does not render when closed', () => {
    const { queryByRole } = render(BundleModal, { props: baseProps({ open: false }) });
    expect(queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows each selected atom (kind tag, description, qty, amount) and the summed total', async () => {
    const { findByRole, getByText } = render(BundleModal, { props: baseProps({ atoms: MULTI_ATOMS }) });
    await findByRole('dialog');
    getByText('Sand edges');
    getByText('Steel');
    getByText('2 hour');
    getByText('$60.00');
    getByText('$15.00');
    // Summed total: 60 + 15 = 75.
    getByText('$75.00');
  });

  it('single-atom seed: description/qty/units/price copy from the atom', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, { props: baseProps({ atoms: SINGLE_ATOM }) });
    await findByRole('dialog');
    expect(await findByLabelText(/Description/)).toHaveValue('Sand edges');
    expect(await findByLabelText(/Quantity/)).toHaveValue(2);
    expect(await findByLabelText(/Price/)).toHaveValue(30);
  });

  it('mixed multi-atom seed (task + material) stays a lump: description blank, qty=1, price=summed total', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, { props: baseProps({ atoms: MULTI_ATOMS }) });
    await findByRole('dialog');
    expect(await findByLabelText(/Description/)).toHaveValue('');
    expect(await findByLabelText(/Quantity/)).toHaveValue(1);
    expect(await findByLabelText(/Price/)).toHaveValue(75);
  });

  it('uniform multi-atom seed (same-rate, same-unit tasks): qty=summed, units=shared, price=shared rate', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, {
      props: baseProps({ atoms: UNIFORM_TASK_ATOMS }),
    });
    await findByRole('dialog');
    expect(await findByLabelText(/Description/)).toHaveValue('');
    // 4 + 4 + 4 = 12 hours, at the shared $25.00 rate.
    expect(await findByLabelText(/Quantity/)).toHaveValue(12);
    expect(await findByLabelText(/Price/)).toHaveValue(25);
    const units = await findByLabelText(/Units/);
    expect(units).toHaveValue('hour');
    // Uniform seed keeps the invariant true from the start: 12 * $25 = $300 = total.
    const checkbox = await findByLabelText(/keep total/i);
    expect(checkbox.closest('label').textContent).toContain('$300.00');
  });

  it('fractional uniform multi-atom seed rounds the summed qty to two decimals (no binary-float garbage)', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, {
      props: baseProps({ atoms: FRACTIONAL_UNIFORM_TASK_ATOMS }),
    });
    await findByRole('dialog');
    const qtyInput = await findByLabelText(/Quantity/);
    // Exact string, not the "3.3000000000000003" plain float addition would
    // produce (1.1 + 1.1 + 1.1 in IEEE-754 binary floating point).
    expect(qtyInput.value).toBe('3.30');
    expect(qtyInput).toHaveValue(3.3);
  });

  it('POSTs the rounded qty when a fractional uniform bundle is submitted untouched', async () => {
    const { findByRole } = render(BundleModal, {
      props: baseProps({ atoms: FRACTIONAL_UNIFORM_TASK_ATOMS }),
    });
    const dialog = await findByRole('dialog');
    await fireEvent.click(within(dialog).getByRole('button', { name: /create line/i }));

    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/line-items-from-atoms/', {
      atoms: [{ type: 'task', id: 1 }, { type: 'task', id: 2 }, { type: 'task', id: 3 }],
      overrides: { description: '', qty: '3.30', units: 'hour', price: '25.00' },
    });
  });

  it('same rate but differing units is NOT treated as uniform: falls back to the lump seed', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, {
      props: baseProps({ atoms: DIFFERING_UNITS_ATOMS }),
    });
    await findByRole('dialog');
    expect(await findByLabelText(/Quantity/)).toHaveValue(1);
    expect(await findByLabelText(/Price/)).toHaveValue(200); // 100 + 100
  });

  it('keep-total is ON by default and shows the target amount', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, { props: baseProps({ atoms: SINGLE_ATOM }) });
    await findByRole('dialog');
    const checkbox = await findByLabelText(/keep total/i);
    expect(checkbox).toBeChecked();
    expect(checkbox.closest('label').textContent).toContain('$60.00');
  });

  it('keep-total ON: editing qty re-derives price = total / qty', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, { props: baseProps({ atoms: SINGLE_ATOM }) });
    await findByRole('dialog');
    const qtyInput = await findByLabelText(/Quantity/);
    await fireEvent.input(qtyInput, { target: { value: '3' } });
    const priceInput = await findByLabelText(/Price/);
    // total is $60 (2 * $30) -> 60 / 3 = 20.00
    expect(priceInput).toHaveValue(20);
  });

  it('keep-total ON: qty of 0/empty does not divide by zero and leaves price untouched', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, { props: baseProps({ atoms: SINGLE_ATOM }) });
    await findByRole('dialog');
    const qtyInput = await findByLabelText(/Quantity/);
    await fireEvent.input(qtyInput, { target: { value: '0' } });
    const priceInput = await findByLabelText(/Price/);
    expect(priceInput).toHaveValue(30); // unchanged from the seed
  });

  it('editing price directly unchecks keep-total (one-way coupling)', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, { props: baseProps({ atoms: SINGLE_ATOM }) });
    await findByRole('dialog');
    const priceInput = await findByLabelText(/Price/);
    await fireEvent.input(priceInput, { target: { value: '99' } });
    const checkbox = await findByLabelText(/keep total/i);
    expect(checkbox).not.toBeChecked();

    // With keep-total off, editing qty no longer re-derives price.
    const qtyInput = await findByLabelText(/Quantity/);
    await fireEvent.input(qtyInput, { target: { value: '5' } });
    expect(priceInput).toHaveValue(99);
  });

  it('re-checking keep-total re-derives price from the current qty', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, { props: baseProps({ atoms: SINGLE_ATOM }) });
    await findByRole('dialog');
    const priceInput = await findByLabelText(/Price/);
    await fireEvent.input(priceInput, { target: { value: '99' } }); // unchecks
    const checkbox = await findByLabelText(/keep total/i);
    await fireEvent.click(checkbox); // re-check
    expect(checkbox).toBeChecked();
    // qty is still 2 (unchanged) -> total $60 / 2 = 30.00
    expect(priceInput).toHaveValue(30);
  });

  it('disables Create when qty is 0/empty', async () => {
    const { findByRole, findByLabelText } = render(BundleModal, { props: baseProps({ atoms: SINGLE_ATOM }) });
    const dialog = await findByRole('dialog');
    const qtyInput = await findByLabelText(/Quantity/);
    await fireEvent.input(qtyInput, { target: { value: '' } });
    const createBtn = within(dialog).getByRole('button', { name: /create line/i });
    expect(createBtn).toBeDisabled();
  });

  it('Create POSTs {atoms, overrides} built from the authored fields', async () => {
    const onCreated = vi.fn();
    const { findByRole, findByLabelText } = render(BundleModal, {
      props: baseProps({ atoms: MULTI_ATOMS, onCreated }),
    });
    const dialog = await findByRole('dialog');
    await fireEvent.input(await findByLabelText(/Description/), { target: { value: 'Bundled work' } });
    await fireEvent.click(within(dialog).getByRole('button', { name: /create line/i }));

    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/line-items-from-atoms/', {
      atoms: [{ type: 'task', id: 41 }, { type: 'material', id: 9 }],
      overrides: { description: 'Bundled work', qty: '1', units: 'none', price: '75.00' },
    });
    await vi.waitFor(() => expect(onCreated).toHaveBeenCalledWith({ line_item_id: 99 }));
  });

  it('on a 409 conflict, calls onConflict (not onCreated) and does not show the overlay itself', async () => {
    api.post.mockRejectedValueOnce(conflictError());
    const onCreated = vi.fn();
    const onConflict = vi.fn();
    const { findByRole } = render(BundleModal, {
      props: baseProps({ atoms: SINGLE_ATOM, onCreated, onConflict }),
    });
    const dialog = await findByRole('dialog');
    await fireEvent.click(within(dialog).getByRole('button', { name: /create line/i }));

    await vi.waitFor(() => expect(onConflict).toHaveBeenCalled());
    expect(onCreated).not.toHaveBeenCalled();
    // BundleModal delegates 409 handling to the caller (it owns the pool/
    // selection refresh) — no overlay set from inside the modal itself.
    expect(get(overlayMessage)).toBeNull();
  });

  it('calls onClose when Cancel is clicked', async () => {
    const onClose = vi.fn();
    const { findByRole, getByRole } = render(BundleModal, { props: baseProps({ onClose }) });
    await findByRole('dialog');
    await fireEvent.click(getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
