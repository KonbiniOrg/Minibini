import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import ActivityPage from '@/routes/ActivityPage.svelte';

function payload(overrides = {}) {
  return {
    recent_days: 5,
    on_shift: [],
    completed_bleps: [],
    job_events: [],
    po_events: [],
    invoice_events: [],
    ...overrides,
  };
}

beforeEach(() => {
  api.get.mockReset();
});

describe('ActivityPage', () => {
  it('fetches /api/activity/ once on mount', async () => {
    api.get.mockResolvedValue(payload());
    render(ActivityPage);
    // microtask flush
    await Promise.resolve();
    await Promise.resolve();
    expect(api.get).toHaveBeenCalledWith('/api/activity/');
  });

  it('renders an on-shift card with name, clock-in, and linked task + job', async () => {
    api.get.mockResolvedValue(payload({
      on_shift: [{
        user_id: 7,
        user_name: 'Jane Doe',
        shift_start: '2026-06-16T08:01:00Z',
        current_blep: {
          task_id: 42, task_name: 'Cut panels',
          job_id: 13, job_number: 'JOB-2026-0007', job_name: 'Acme cabinets',
          blep_start: '2026-06-16T08:05:00Z',
        },
      }],
    }));
    const { findByText, getByText } = render(ActivityPage);

    expect(await findByText('Jane Doe')).toBeInTheDocument();
    expect(getByText(/since/i)).toBeInTheDocument();

    const taskLink = getByText('Cut panels').closest('a');
    expect(taskLink).toHaveAttribute('href', '/jobs/13/tasks/42');

    const jobLink = getByText(/JOB-2026-0007/).closest('a');
    expect(jobLink).toHaveAttribute('href', '/jobs/13');
  });

  it('renders an idle card with no task/job links when current_blep is null', async () => {
    api.get.mockResolvedValue(payload({
      on_shift: [{
        user_id: 8, user_name: 'Sam Idle',
        shift_start: '2026-06-16T07:30:00Z', current_blep: null,
      }],
    }));
    const { findByText, container } = render(ActivityPage);

    const card = (await findByText('Sam Idle')).closest('.shift-card');
    expect(card).toBeTruthy();
    expect(card.textContent).toMatch(/idle/i);
    expect(card.querySelector('a')).toBeNull();
  });

  it('renders job, po, and invoice event rows', async () => {
    api.get.mockResolvedValue(payload({
      job_events: [
        { kind: 'estimate_sent', job_id: 13, job_number: 'JOB-2026-0007', job_name: 'Acme', estimate_id: 88, date: '2026-06-14' },
        { kind: 'job_approved', job_id: 14, job_number: 'JOB-2026-0008', job_name: 'Beta', date: '2026-06-15' },
      ],
      po_events: [
        { kind: 'sent', po_id: 5, po_number: 'PO-2026-0003', date: '2026-06-13' },
        { kind: 'received', po_id: 6, po_number: 'PO-2026-0004', date: '2026-06-12' },
      ],
      invoice_events: [
        { kind: 'sent', invoice_id: 9, invoice_number: 'INV-2026-0002', display_number: 'INV-2026-0002', date: '2026-06-11' },
        { kind: 'paid', invoice_id: 10, invoice_number: 'INV-2026-0005', display_number: 'INV-2026-0005', date: '2026-06-10' },
      ],
    }));
    const { findByText, getByText } = render(ActivityPage);

    expect((await findByText(/JOB-2026-0007/)).closest('a')).toHaveAttribute('href', '/jobs/13');
    expect(getByText(/estimate sent/i)).toBeInTheDocument();
    expect(getByText(/JOB-2026-0008/).closest('a')).toHaveAttribute('href', '/jobs/14');
    expect(getByText(/approved/i)).toBeInTheDocument();

    expect(getByText(/PO-2026-0003/).closest('a')).toHaveAttribute('href', '/purchase-orders/5');
    expect(getByText(/PO-2026-0004/).closest('a')).toHaveAttribute('href', '/purchase-orders/6');

    expect(getByText(/INV-2026-0002/).closest('a')).toHaveAttribute('href', '/invoices/9');
    expect(getByText(/INV-2026-0005/).closest('a')).toHaveAttribute('href', '/invoices/10');
  });

  it('shows empty-state lines for each event section with the recent_days window', async () => {
    api.get.mockResolvedValue(payload({ recent_days: 5 }));
    const { findByText, getByText } = render(ActivityPage);

    expect(await findByText(/No job or estimate activity in the last 5 days/i)).toBeInTheDocument();
    expect(getByText(/No purchase order activity in the last 5 days/i)).toBeInTheDocument();
    expect(getByText(/No invoice activity in the last 5 days/i)).toBeInTheDocument();
  });

  it('renders the completed-work table fed completed_bleps', async () => {
    api.get.mockResolvedValue(payload({
      completed_bleps: [{
        blep_id: 1, user_name: 'Pat', task_name: 'Sanding', task: 3,
        job_id: 7, job_number: 'JOB-7', job_name: 'Widget',
        start_time: '2026-06-16T14:00:00', end_time: '2026-06-16T15:00:00',
      }],
    }));
    const { findByText } = render(ActivityPage);
    expect(await findByText('Sanding')).toBeInTheDocument();
    expect(await findByText('Pat')).toBeInTheDocument();
  });

  it('shows an empty-state for completed work when there are none', async () => {
    api.get.mockResolvedValue(payload({ recent_days: 5 }));
    const { findByText } = render(ActivityPage);
    expect(await findByText(/No completed work in the last 5 days/i)).toBeInTheDocument();
  });
});
