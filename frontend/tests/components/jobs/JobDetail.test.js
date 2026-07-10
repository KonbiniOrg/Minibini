import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, within } from '@testing-library/svelte';

// The context band lazily fetches emails when expanded; every api.get resolves
// to an empty list so the band (and any other child fetch) is tolerated.
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobDetail from '@/components/jobs/JobDetail.svelte';

const NOW = new Date('2026-07-09T12:00:00');

const SPEC_ORDER = ['Scope', 'Work', 'Materials', 'Spend', 'Invoicing', 'Delivery'];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]); // context band's lazy email fetch, etc.
  api.post.mockReset();
  user.set({ permissions: ['can_manage_jobs'] });
});

// A mid-production job: estimate accepted (Scope frozen), work in progress
// (Work active), nothing else started.
function midProductionProps() {
  return {
    job: {
      job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress',
      can_manage: true, estimated_amount: '12400.00', materials: [],
    },
    estimates: { results: [{
      estimate_id: 1, estimate_number: 'EST-1', version: 2, status: 'accepted',
      closed_date: '2026-06-12', total: '12400.00', line_items: [],
    }] },
    changeOrders: [],
    invoices: { results: [] },
    purchaseOrders: { results: [] },
    shipments: [],
    deliverableCount: 0,
    overview: {
      due: null,
      spend: { labor: '0', labor_hours: '0.0', materials_bought: '0', total: '0' },
      work: {
        tasks_total: 14, tasks_complete: 9, tasks_blocked: 0, tasks_terminal: 0,
        est_time_total_hours: '0.0', est_time_complete_hours: '0.0', working_now: [],
      },
    },
    now: NOW,
  };
}

describe('JobDetail — six-block lifecycle summary', () => {
  it('mounts through JobShell (header renders, nav rail present)', () => {
    const { getByText, container } = render(JobDetail, { props: midProductionProps() });
    // JobHeader renders inside the shell.
    expect(getByText(/JOB #5/)).toBeInTheDocument();
    // JobNavRail renders the Overview section link.
    expect(container.querySelector('.summary-blocks')).not.toBeNull();
  });

  it('renders the six lifecycle blocks in spec order', () => {
    const { container } = render(JobDetail, { props: midProductionProps() });
    const titles = [...container.querySelectorAll('.summary-blocks .summary-block-title')]
      .map((el) => el.textContent.trim());
    expect(titles).toEqual(SPEC_ORDER);
  });

  it('threads props: accepted estimate → Scope frozen, in-progress work → Work active', () => {
    const { container } = render(JobDetail, { props: midProductionProps() });
    const blocks = [...container.querySelectorAll('.summary-blocks .summary-block')];
    const scope = blocks.find((b) => within(b).queryByText('Scope'));
    const work = blocks.find((b) => within(b).queryByText('Work'));
    expect(scope.classList.contains('frozen')).toBe(true);
    // The frozen Scope line carries the accepted estimate facts.
    expect(scope.textContent).toContain('v2 accepted');
    expect(work.classList.contains('active')).toBe(true);
  });

  it('has no accordion pillars left', () => {
    const { container, queryByText } = render(JobDetail, { props: midProductionProps() });
    expect(container.querySelector('.accordion')).toBeNull();
    expect(container.querySelector('.pillar')).toBeNull();
    expect(queryByText('Tasks & Materials')).toBeNull();
  });

  it('still renders the latest-change-request banner above the blocks (draft job)', () => {
    const props = {
      job: {
        job_id: 9, job_number: 'JOB-9', name: 'Revised', status: 'draft',
        can_manage: true, estimated_amount: '0', materials: [],
        latest_change_request: { text: 'Please shorten the legs' },
      },
      estimates: { results: [] },
      changeOrders: [],
      invoices: { results: [] },
      purchaseOrders: { results: [] },
      shipments: [],
      deliverableCount: 0,
      overview: { due: null, spend: {}, work: {} },
      now: NOW,
    };
    const { getByText, container } = render(JobDetail, { props });
    const banner = container.querySelector('.change-request-banner');
    expect(banner).not.toBeNull();
    expect(getByText(/Please shorten the legs/)).toBeInTheDocument();
    // Banner precedes the blocks in document order.
    const blocks = container.querySelector('.summary-blocks');
    expect(banner.compareDocumentPosition(blocks) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });
});

describe('JobDetail — Materials coverage signal', () => {
  function propsWith(materials) {
    const p = midProductionProps();
    p.job.materials = materials;
    // Force an open PO so the Materials block is active and shows Coverage.
    p.purchaseOrders = { results: [{
      po_id: 1, po_number: 'PO-1', status: 'issued', business_name: 'Acme',
      issued_date: '2026-07-01', requested_date: '2026-07-15', line_items: [],
    }] };
    return p;
  }

  it('flags SHORT when a material needs ordering', () => {
    const props = propsWith([
      { material_id: 1, description: 'Steel', quantity: '10', qty_on_hand: '0',
        qty_on_order: '0', inventory_item: 42, cost_source: 'estimated',
        consumption_state: 'pending', po_line_item_id: null },
    ]);
    const { container } = render(JobDetail, { props });
    const blocks = [...container.querySelectorAll('.summary-blocks .summary-block')];
    const materials = blocks.find((b) => within(b).queryByText('Materials'));
    expect(materials.textContent).toContain('SHORT');
  });

  it('reads OK when stock covers every material', () => {
    const props = propsWith([
      { material_id: 1, description: 'Steel', quantity: '10', qty_on_hand: '20',
        qty_on_order: '0', inventory_item: 42, cost_source: 'estimated',
        consumption_state: 'pending', po_line_item_id: null },
    ]);
    const { container } = render(JobDetail, { props });
    const blocks = [...container.querySelectorAll('.summary-blocks .summary-block')];
    const materials = blocks.find((b) => within(b).queryByText('Materials'));
    expect(materials.textContent).toContain('OK');
  });
});
