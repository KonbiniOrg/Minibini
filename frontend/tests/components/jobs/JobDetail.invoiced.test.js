import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobDetail from '@/components/jobs/JobDetail.svelte';

const NOW = new Date('2026-07-09T12:00:00');

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]);
  api.post.mockReset();
  user.set({ permissions: [] });
});

function baseProps(overrides = {}) {
  return {
    job: {
      job_id: 1, job_number: 'JOB-1', name: 'J', status: 'in_progress',
      can_manage: false, estimated_amount: '1000.00', materials: [],
    },
    estimates: { results: [] },
    changeOrders: [],
    invoices: { results: [] },
    purchaseOrders: { results: [] },
    shipments: [],
    deliverableCount: 0,
    overview: { due: null, spend: {}, work: {} },
    now: NOW,
    ...overrides,
  };
}

function invoicingBlock(container) {
  const blocks = [...container.querySelectorAll('.summary-blocks .summary-block')];
  return blocks.find((b) => within(b).queryByText('Invoicing'));
}

describe('JobDetail — Invoicing block', () => {
  it('is dormant ("none yet") when the job has no invoices', () => {
    const { container } = render(JobDetail, { props: baseProps() });
    const block = invoicingBlock(container);
    expect(block.classList.contains('dormant')).toBe(true);
    expect(block.textContent).toContain('none yet');
  });

  it('activates and reads the server-supplied invoice total', () => {
    const props = baseProps({
      invoices: { results: [{
        invoice_id: 3, invoice_number: 'INV-3', display_number: 'INV-3', status: 'open',
        sent_date: '2026-07-01', closed_date: null, total: '400.00',
      }] },
    });
    const { container } = render(JobDetail, { props });
    const block = invoicingBlock(container);
    expect(block.classList.contains('active')).toBe(true);
    expect(block.textContent).toContain('INV-3');
    expect(block.textContent).toContain('$400');
  });

  it('no longer renders per-atom "Invoiced ·" links (the pillar tables are gone)', () => {
    const props = baseProps({
      job: {
        job_id: 1, job_number: 'JOB-1', name: 'J', status: 'in_progress',
        can_manage: false, estimated_amount: '1000.00',
        materials: [{ material_id: 11, description: 'Steel', quantity: '1',
                      invoice: { id: 5, number: 'INV-5' } }],
        tasks: [{ task_id: 7, name: 'Cut', status: 'complete',
                  invoice: { id: 3, number: 'INV-3' } }],
      },
    });
    const { queryByRole } = render(JobDetail, { props });
    expect(queryByRole('link', { name: /Invoiced/ })).toBeNull();
  });
});
