import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { post: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import DriftModal from '@/components/docsurface/DriftModal.svelte';

// A drifted task claim — the numbers from the spec's own example:
// 0.75 hour per unit x 10 units = 7.50 hour, but the task's live est_qty
// (qty_display) has since diverged to 8 hour.
const TASK_ATOM = {
  kind: 'task',
  description: 'Cut chair parts',
  qty_display: '8 hour',
  qty: '8',
  units: 'hour',
  rate: '20.00',
  amount: '160.00',
  source_id: 501,
  per_unit_qty: '0.75',
  expected_total: '7.50',
  drift: true,
};

// Same claim, but the per-unit bundle also snapshotted a schedule
// commitment (per_unit_worker_time) — expected_worker_time is the
// multiplied-out expectation, DRF-DurationField style ("HH:MM:SS").
const TASK_ATOM_WITH_SCHEDULE = {
  ...TASK_ATOM,
  expected_worker_time: '07:30:00',
};

const MATERIAL_ATOM = {
  kind: 'material',
  description: 'Oak seat blank',
  qty_display: '32 BF',
  qty: '32',
  units: 'BF',
  rate: '5.00',
  amount: '160.00',
  source_id: 502,
  per_unit_qty: '3',
  expected_total: '30',
  drift: true,
};

function baseProps(overrides = {}) {
  return {
    open: true,
    atom: TASK_ATOM,
    lineQty: 10,
    apiBase: '/api/estimates/7',
    onReverted: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({ message: 'Atom restamped to the per-unit agreement.' });
});

describe('DriftModal', () => {
  it('does not render when closed', () => {
    const { queryByRole } = render(DriftModal, { props: baseProps({ open: false }) });
    expect(queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('spells out the agreement expectation with the actual numbers', async () => {
    const { findByRole } = render(DriftModal, { props: baseProps() });
    const dialog = await findByRole('dialog');
    expect(dialog.textContent).toContain('0.75 hour');
    expect(dialog.textContent).toContain('10 units');
    expect(dialog.textContent).toContain('7.50 hour');
  });

  it('shows the atom\'s current value', async () => {
    const { findByRole } = render(DriftModal, { props: baseProps() });
    const dialog = await findByRole('dialog');
    expect(dialog.textContent).toContain('8 hour');
  });

  it('names the task, never says "atom"', async () => {
    const { findByRole } = render(DriftModal, { props: baseProps() });
    const dialog = await findByRole('dialog');
    expect(dialog.textContent).toContain('Cut chair parts');
    expect(dialog.textContent.toLowerCase()).not.toContain('atom');
  });

  it('shows the expected schedule time when the claim snapshotted one', async () => {
    const { findByRole } = render(DriftModal, {
      props: baseProps({ atom: TASK_ATOM_WITH_SCHEDULE }),
    });
    const dialog = await findByRole('dialog');
    expect(dialog.textContent).toContain('7h 30m');
  });

  it('omits schedule-time copy when the claim never snapshotted one', async () => {
    const { findByRole } = render(DriftModal, { props: baseProps() });
    const dialog = await findByRole('dialog');
    expect(dialog.textContent).not.toContain('schedule');
  });

  it('adds the physical-material sentence for a material atom', async () => {
    const { findByRole } = render(DriftModal, { props: baseProps({ atom: MATERIAL_ATOM }) });
    const dialog = await findByRole('dialog');
    expect(dialog.textContent).toContain('physical material');
    expect(dialog.textContent).toContain('does not undo purchasing or stock decisions');
  });

  it('never shows the physical-material sentence for a task atom', async () => {
    const { findByRole } = render(DriftModal, { props: baseProps() });
    const dialog = await findByRole('dialog');
    expect(dialog.textContent).not.toContain('physical material');
  });

  it('Revert to agreement POSTs the source_id to the restamp endpoint, then reverts+closes', async () => {
    const onReverted = vi.fn();
    const { findByRole, getByRole } = render(DriftModal, { props: baseProps({ onReverted }) });
    await findByRole('dialog');
    await fireEvent.click(getByRole('button', { name: /revert to agreement/i }));

    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/restamp-atom/', { source_id: 501 });
    await vi.waitFor(() => expect(onReverted).toHaveBeenCalledTimes(1));
  });

  it('uses the change-order apiBase when wired from a CO surface', async () => {
    const { findByRole, getByRole } = render(DriftModal, {
      props: baseProps({ apiBase: '/api/change-orders/12' }),
    });
    await findByRole('dialog');
    await fireEvent.click(getByRole('button', { name: /revert to agreement/i }));
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/12/restamp-atom/', { source_id: 501 });
  });

  it('never mutates on open — no POST fires until Revert is clicked', async () => {
    const { findByRole } = render(DriftModal, { props: baseProps() });
    await findByRole('dialog');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('Cancel calls onClose without posting anything', async () => {
    const onClose = vi.fn();
    const { findByRole, getByRole } = render(DriftModal, { props: baseProps({ onClose }) });
    await findByRole('dialog');
    await fireEvent.click(getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('routes a failed revert through triageError into an in-modal FormMessage, not an alert', async () => {
    api.post.mockRejectedValueOnce(
      Object.assign(new Error('nope'), { status: 400, data: { detail: 'That claim is not a per-unit claim.' } })
    );
    const onReverted = vi.fn();
    const { findByRole, getByRole, findByText } = render(DriftModal, { props: baseProps({ onReverted }) });
    await findByRole('dialog');
    await fireEvent.click(getByRole('button', { name: /revert to agreement/i }));

    await findByText('That claim is not a per-unit claim.');
    expect(onReverted).not.toHaveBeenCalled();
  });
});
