import { describe, it, expect } from 'vitest';
import {
  RESPONSE_CLOCK_DAYS,
  DUE_PRESSURE_WORKING_DAYS,
  PICKUP_CLOCK_WORKING_DAYS,
  INVOICE_ROW_MAX,
  scopeBlock,
  workBlock,
  materialsBlock,
  spendBlock,
  invoicingBlock,
  deliveryBlock,
} from '../../src/lib/jobOverview.js';

// ---------------------------------------------------------------------------
// Threshold constants (the spec's "clock thresholds ship as constants")
// ---------------------------------------------------------------------------
describe('threshold constants', () => {
  it('match the spec', () => {
    expect(RESPONSE_CLOCK_DAYS).toBe(7);
    expect(DUE_PRESSURE_WORKING_DAYS).toBe(5);
    expect(PICKUP_CLOCK_WORKING_DAYS).toBe(3);
    expect(INVOICE_ROW_MAX).toBe(4);
  });
});

// small helper to pull a stat by label out of a block result
const stat = (block, label) => block.stats.find((s) => s.label === label);

// ===========================================================================
// 1. SCOPE
// ===========================================================================
describe('scopeBlock', () => {
  it('dormant — no estimate, no deliverables', () => {
    const b = scopeBlock({ estimates: [], changeOrders: [], deliverableCount: 0, now: '2025-07-09' });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('no estimate yet');
  });

  it('dormant — no estimate, with deliverables clause', () => {
    const b = scopeBlock({ estimates: [], changeOrders: [], deliverableCount: 3, now: '2025-07-09' });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('no estimate yet · 3 deliverables defined');
  });

  it('active — open estimate with superseded prior, sent + response clock (red ≥7)', () => {
    const b = scopeBlock({
      estimates: [
        { version: 1, status: 'superseded' },
        { version: 2, status: 'open', sent_date: '2025-06-27', total: '8750.00' },
      ],
      changeOrders: [],
      deliverableCount: 3,
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    const est = stat(b, 'Estimate');
    expect(est.value).toBe('v2');
    expect(est.pill).toEqual({ text: 'OPEN', tone: 'open' });
    expect(est.sub).toBe('v1 superseded');
    expect(stat(b, 'Total').value).toBe('$8,750');
    expect(stat(b, 'Sent').value).toBe('Jun 27');
    expect(stat(b, 'Change orders').value).toBe('—');
    expect(stat(b, 'Deliverables').value).toBe('3');
    // 06-27 → 07-09 = 12 days → red
    expect(b.clock).toEqual({ tone: 'bad', lines: ['No customer response in 12 days'] });
  });

  it('active — draft estimate has no response clock', () => {
    const b = scopeBlock({
      estimates: [{ version: 1, status: 'draft', total: '5000.00' }],
      changeOrders: [],
      deliverableCount: 0,
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    expect(stat(b, 'Estimate').pill).toEqual({ text: 'DRAFT', tone: 'draft' });
    expect(b.clock).toBeUndefined();
  });

  it('response clock is quiet at 6 days, red at 7', () => {
    const quiet = scopeBlock({
      estimates: [{ version: 1, status: 'open', sent_date: '2025-07-03', total: '1.00' }],
      changeOrders: [], deliverableCount: 0, now: '2025-07-09',
    });
    expect(quiet.clock).toEqual({ tone: 'neutral', lines: ['No customer response in 6 days'] });
    const red = scopeBlock({
      estimates: [{ version: 1, status: 'open', sent_date: '2025-07-02', total: '1.00' }],
      changeOrders: [], deliverableCount: 0, now: '2025-07-09',
    });
    expect(red.clock).toEqual({ tone: 'bad', lines: ['No customer response in 7 days'] });
  });

  it('frozen — accepted estimate + accepted CO updates total and appends fact', () => {
    const b = scopeBlock({
      estimates: [{ version: 3, status: 'accepted', closed_date: '2025-06-12', total: '12000.00' }],
      changeOrders: [
        { change_order_number: 'CO-1', status: 'accepted', closed_date: '2025-06-30', total: '400.00' },
      ],
      deliverableCount: 3,
      now: '2025-07-09',
    });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toBe('$12,400 · v3 accepted 6/12 · CO-1 accepted 6/30 · 3 deliverables');
  });

  it('frozen — rejected estimate leads with the version fact', () => {
    const b = scopeBlock({
      estimates: [{ version: 2, status: 'rejected', closed_date: '2025-06-05', total: '9000.00' }],
      changeOrders: [],
      deliverableCount: 0,
      now: '2025-07-09',
    });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toBe('v2 rejected 6/5');
  });

  it('a draft/open CO re-activates a frozen scope and runs the CO response clock', () => {
    const b = scopeBlock({
      estimates: [{ version: 3, status: 'accepted', closed_date: '2025-06-12', total: '12000.00' }],
      changeOrders: [
        { change_order_number: 'CO-2', status: 'open', sent_date: '2025-07-01', total: '500.00' },
      ],
      deliverableCount: 3,
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    const co = stat(b, 'Change order');
    expect(co.value).toBe('CO-2');
    expect(co.pill).toEqual({ text: 'OPEN', tone: 'open' });
    expect(co.sub).toBe('+$500');
    expect(stat(b, 'Estimate').value).toBe('v3');
    expect(stat(b, 'Estimate').pill).toEqual({ text: 'ACCEPTED', tone: 'accepted' });
    expect(stat(b, 'Total').value).toBe('$12,000');
    // CO sent 07-01 → now 07-09 = 8 days → red
    expect(b.clock).toEqual({ tone: 'bad', lines: ['No customer response in 8 days'] });
  });

  it('a negative-total CO renders its own sign, not a "+-" double sign (T8)', () => {
    const b = scopeBlock({
      estimates: [{ version: 3, status: 'accepted', closed_date: '2025-06-12', total: '12000.00' }],
      changeOrders: [
        { change_order_number: 'CO-2', status: 'open', sent_date: '2025-07-01', total: '-500.00' },
      ],
      deliverableCount: 3,
      now: '2025-07-09',
    });
    const co = stat(b, 'Change order');
    expect(co.sub).toBe('-$500');
  });

  it('CO response clock quiet at 6 days', () => {
    const b = scopeBlock({
      estimates: [{ version: 1, status: 'accepted', closed_date: '2025-06-01', total: '100.00' }],
      changeOrders: [
        { change_order_number: 'CO-1', status: 'open', sent_date: '2025-07-03', total: '10.00' },
      ],
      deliverableCount: 0,
      now: '2025-07-09',
    });
    expect(b.clock).toEqual({ tone: 'neutral', lines: ['No customer response in 6 days'] });
  });

  it('a draft CO reactivates a frozen scope with no response clock (not yet sent)', () => {
    const b = scopeBlock({
      estimates: [{ version: 3, status: 'accepted', closed_date: '2025-06-12', total: '12000.00' }],
      changeOrders: [
        { change_order_number: 'CO-3', status: 'draft', total: '250.00' },
      ],
      deliverableCount: 0,
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    const co = stat(b, 'Change order');
    expect(co.value).toBe('CO-3');
    expect(co.pill).toEqual({ text: 'DRAFT', tone: 'draft' });
    expect(b.clock).toBeUndefined();
  });

  it('a new higher-version draft (revision) reactivates a frozen scope', () => {
    const b = scopeBlock({
      estimates: [
        { version: 1, status: 'accepted', closed_date: '2025-06-01', total: '9000.00' },
        { version: 2, status: 'draft', total: '9500.00' },
      ],
      changeOrders: [],
      deliverableCount: 0,
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    const est = stat(b, 'Estimate');
    expect(est.value).toBe('v2');
    expect(est.pill).toEqual({ text: 'DRAFT', tone: 'draft' });
  });
});

// ===========================================================================
// 2. WORK
// ===========================================================================
const overviewMid = {
  due: { date: '2025-07-24', working_days_left: 11 },
  spend: { labor: '2340.00', labor_hours: '41.5', materials_bought: '1176.00', total: '3516.00' },
  work: {
    tasks_total: 14, tasks_complete: 9, tasks_blocked: 1, tasks_terminal: 10,
    est_time_total_hours: '64.0', est_time_complete_hours: '41.0',
    working_now: [{ task_name: 'CNC cut shelving parts', worker_name: 'Dana' }],
  },
};

describe('workBlock', () => {
  it('dormant — not approved, tasks planned ahead', () => {
    const b = workBlock({
      job: { status: 'submitted' },
      overview: { work: { tasks_total: 0 } },
      tasksPlanned: 8,
    });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('8 tasks planned · starts when the scope is accepted');
  });

  it('dormant — not approved, no tasks planned', () => {
    const b = workBlock({
      job: { status: 'submitted' },
      overview: { work: { tasks_total: 0 } },
      tasksPlanned: 0,
    });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('starts when the scope is accepted');
  });

  it('active — progress by est time, tasks, due, working-now clock', () => {
    const b = workBlock({ job: { status: 'in_progress' }, overview: overviewMid, tasksPlanned: 0 });
    expect(b.state).toBe('active');
    const p = stat(b, 'Progress · by estimated time');
    expect(p.value).toBe('64%');
    expect(p.unit).toBe('41h of 64h');
    expect(p.bar).toBe(64);
    const t = stat(b, 'Tasks');
    expect(t.value).toBe('9');
    expect(t.unit).toBe(' / 14');
    expect(t.sub).toBe('1 BLOCKED');
    expect(t.subTone).toBe('bad');
    const d = stat(b, 'Due');
    expect(d.value).toBe('7/24');
    // 11 working days > 5 → neutral (spec: amber only within 5)
    expect(d.subTone).toBe('neutral');
    expect(d.sub).toBe('11 working days left');
    expect(b.clock).toEqual({ tone: 'good', lines: ['● Dana working now — CNC cut shelving parts'] });
  });

  it('active — blocked pill omitted when zero blocked', () => {
    const ov = { ...overviewMid, work: { ...overviewMid.work, tasks_blocked: 0 } };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    expect(stat(b, 'Tasks').sub).toBeUndefined();
  });

  it('active — due within 5 working days is amber', () => {
    const ov = { ...overviewMid, due: { date: '2025-07-14', working_days_left: 4 } };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    const d = stat(b, 'Due');
    expect(d.sub).toBe('4 working days left');
    expect(d.subTone).toBe('warn');
    expect(d.valueTone).toBe('warn');
  });

  it('active — overdue copy and red tone', () => {
    const ov = { ...overviewMid, due: { date: '2025-07-04', working_days_left: -3 } };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    const d = stat(b, 'Due');
    expect(d.sub).toBe('overdue by 3 working days');
    expect(d.subTone).toBe('bad');
    expect(d.valueTone).toBe('bad');
  });

  it('active — due pressure boundary: exactly 5 working days left is amber', () => {
    const ov = { ...overviewMid, due: { date: '2025-07-16', working_days_left: 5 } };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    const d = stat(b, 'Due');
    expect(d.subTone).toBe('warn');
    expect(d.valueTone).toBe('warn');
  });

  it('active — due pressure boundary: due today (0 working days left) is amber, not red', () => {
    const ov = { ...overviewMid, due: { date: '2025-07-09', working_days_left: 0 } };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    const d = stat(b, 'Due');
    expect(d.subTone).toBe('warn');
    expect(d.valueTone).toBe('warn');
  });

  it('active — due stat omitted without a due date', () => {
    const ov = { ...overviewMid, due: null };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    expect(stat(b, 'Due')).toBeUndefined();
  });

  it('active — count fallback when no est time', () => {
    const ov = { ...overviewMid, work: { ...overviewMid.work, est_time_total_hours: '0.0', est_time_complete_hours: '0.0' } };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    const p = stat(b, 'Progress · by task count');
    expect(p.value).toBe('64%'); // 9/14
    expect(p.unit).toBe('9 of 14');
    expect(p.bar).toBe(64);
  });

  it('active — multiple workers produce multiple clock lines', () => {
    const ov = {
      ...overviewMid,
      work: {
        ...overviewMid.work,
        working_now: [
          { task_name: 'CNC cut', worker_name: 'Dana' },
          { task_name: 'Sand panels', worker_name: 'Sam' },
        ],
      },
    };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    expect(b.clock.lines).toEqual([
      '● Dana working now — CNC cut',
      '● Sam working now — Sand panels',
    ]);
  });

  it('active — no working-now means no clock', () => {
    const ov = { ...overviewMid, work: { ...overviewMid.work, working_now: [] } };
    const b = workBlock({ job: { status: 'in_progress' }, overview: ov, tasksPlanned: 0 });
    expect(b.clock).toBeUndefined();
  });

  it('frozen — work complete', () => {
    const ov = {
      due: null,
      spend: { labor: '2340.00', labor_hours: '64.0', materials_bought: '0', total: '2340.00' },
      work: {
        tasks_total: 14, tasks_complete: 14, tasks_blocked: 0, tasks_terminal: 14,
        est_time_total_hours: '64.0', est_time_complete_hours: '64.0', working_now: [],
      },
    };
    const b = workBlock({ job: { status: 'work_complete' }, overview: ov, tasksPlanned: 0 });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toBe('14 tasks · 64h logged');
  });

  it('frozen — cancelled job renders the same facts line as work_complete', () => {
    const ov = {
      due: null,
      spend: { labor: '2340.00', labor_hours: '64.0', materials_bought: '0', total: '2340.00' },
      work: {
        tasks_total: 14, tasks_complete: 14, tasks_blocked: 0, tasks_terminal: 14,
        est_time_total_hours: '64.0', est_time_complete_hours: '64.0', working_now: [],
      },
    };
    const b = workBlock({ job: { status: 'cancelled' }, overview: ov, tasksPlanned: 0 });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toBe('14 tasks · 64h logged');
  });

  it('frozen — rejected job renders the same facts line as work_complete', () => {
    const ov = {
      due: null,
      spend: { labor: '2340.00', labor_hours: '64.0', materials_bought: '0', total: '2340.00' },
      work: {
        tasks_total: 14, tasks_complete: 14, tasks_blocked: 0, tasks_terminal: 14,
        est_time_total_hours: '64.0', est_time_complete_hours: '64.0', working_now: [],
      },
    };
    const b = workBlock({ job: { status: 'rejected' }, overview: ov, tasksPlanned: 0 });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toBe('14 tasks · 64h logged');
  });
});

// ===========================================================================
// 3. MATERIALS
// ===========================================================================
describe('materialsBlock', () => {
  it('dormant — nothing on order', () => {
    const b = materialsBlock({ pos: [], materials: [] });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('nothing on order');
  });

  it('active — open PO line + received + coverage', () => {
    const b = materialsBlock({
      pos: [
        { po_number: 'PO-0031', status: 'issued', business_name: 'Plywood Supply Co', issued_date: '2025-06-28', requested_date: '2025-07-10' },
        { po_number: 'PO-0027', status: 'received_in_full', received_date: '2025-06-30' },
      ],
      materials: [{ inventory_item: 7, cost_source: 'entered', consumption_state: 'pending',
                    quantity: '4.00', qty_on_hand: '4.00' }],
    });
    expect(b.state).toBe('active');
    const on = stat(b, 'On order');
    expect(on.value).toBe('PO-0031');
    expect(on.sub).toBe('Plywood Supply Co · sent 6/28');
    expect(stat(b, 'Due').value).toBe('7/10');
    const rec = stat(b, 'Received');
    expect(rec.value).toBe('1');
    expect(rec.unit).toBe(' PO');
    const cov = stat(b, 'Coverage');
    expect(cov.value).toBe('OK');
    expect(cov.valueTone).toBe('good');
    expect(cov.sub).toBeUndefined();
  });

  it('active — coverage short with no open PO', () => {
    const b = materialsBlock({
      pos: [{ po_number: 'PO-0027', status: 'received_in_full', received_date: '2025-06-30' }],
      materials: [{ inventory_item: 7, cost_source: 'entered', consumption_state: 'pending',
                    quantity: '4.00', qty_on_hand: '0.00' }],
    });
    expect(b.state).toBe('active');
    expect(stat(b, 'Coverage').value).toBe('SHORT');
  });

  it('frozen — all received', () => {
    const b = materialsBlock({
      pos: [
        { po_number: 'PO-0027', status: 'received_in_full' },
        { po_number: 'PO-0028', status: 'received_in_full' },
        { po_number: 'PO-0029', status: 'received_in_full' },
      ],
      coverage: { label: 'OK', tone: 'good' },
    });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toBe('3 POs, all received');
  });

  it('frozen — single received PO pluralizes correctly', () => {
    const b = materialsBlock({
      pos: [{ po_number: 'PO-0027', status: 'received_in_full' }],
      coverage: null,
    });
    expect(b.frozenText).toBe('1 PO, all received');
  });

  it('dormant — only cancelled POs, no received, no shortfall', () => {
    const b = materialsBlock({
      pos: [{ po_number: 'PO-0099', status: 'cancelled' }],
      coverage: null,
    });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('nothing on order');
  });

  it('PO due pressure — due tomorrow is amber', () => {
    const b = materialsBlock({
      pos: [
        { po_number: 'PO-0031', status: 'issued', business_name: 'Plywood Supply Co', issued_date: '2025-06-28', requested_date: '2025-07-10' },
      ],
      coverage: null,
      now: '2025-07-09',
    });
    const due = stat(b, 'Due');
    expect(due.value).toBe('7/10');
    expect(due.valueTone).toBe('warn');
  });

  it('PO due pressure — past due is red', () => {
    const b = materialsBlock({
      pos: [
        { po_number: 'PO-0031', status: 'issued', business_name: 'Plywood Supply Co', issued_date: '2025-06-28', requested_date: '2025-07-05' },
      ],
      coverage: null,
      now: '2025-07-09',
    });
    const due = stat(b, 'Due');
    expect(due.valueTone).toBe('bad');
  });

  it('PO due pressure — due in 10 days has no tone', () => {
    const b = materialsBlock({
      pos: [
        { po_number: 'PO-0031', status: 'issued', business_name: 'Plywood Supply Co', issued_date: '2025-06-28', requested_date: '2025-07-19' },
      ],
      coverage: null,
      now: '2025-07-09',
    });
    const due = stat(b, 'Due');
    expect(due.valueTone).toBeUndefined();
  });

  it('PO due pressure — boundary exactly 5 days out is amber', () => {
    const b = materialsBlock({
      pos: [
        { po_number: 'PO-0031', status: 'issued', business_name: 'Plywood Supply Co', issued_date: '2025-06-28', requested_date: '2025-07-14' },
      ],
      coverage: null,
      now: '2025-07-09',
    });
    const due = stat(b, 'Due');
    expect(due.valueTone).toBe('warn');
  });
});

// ===========================================================================
// 4. SPEND
// ===========================================================================
describe('spendBlock', () => {
  it('dormant — nothing spent', () => {
    const b = spendBlock({
      job: { status: 'approved' },
      overview: { spend: { labor: '0.00', labor_hours: '0.0', materials_bought: '0.00', total: '0.00' } },
      scopeTotal: 12400,
    });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('nothing spent yet');
  });

  it('active — labor/materials/total split with scope percent', () => {
    const b = spendBlock({ job: { status: 'in_progress' }, overview: overviewMid, scopeTotal: 12400 });
    expect(b.state).toBe('active');
    expect(stat(b, 'Labor').value).toBe('$2,340');
    expect(stat(b, 'Labor').sub).toBe('41.5 hours');
    expect(stat(b, 'Materials').value).toBe('$1,176');
    expect(stat(b, 'Materials').sub).toBe('bought so far');
    const t = stat(b, 'Total spent');
    expect(t.value).toBe('$3,516');
    expect(t.sub).toBe('28% of the $12,400 scope');
  });

  it('frozen — terminal job shows the three figures', () => {
    const b = spendBlock({ job: { status: 'completed' }, overview: overviewMid, scopeTotal: 12400 });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toContain('$2,340');
    expect(b.frozenText).toContain('$1,176');
    expect(b.frozenText).toContain('$3,516');
  });
});

// ===========================================================================
// 5. INVOICING
// ===========================================================================
describe('invoicingBlock', () => {
  it('dormant — no invoices', () => {
    const b = invoicingBlock({ invoices: [], scopeTotal: 12400, now: '2025-07-09' });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('none yet');
  });

  it('active — paid-latency clock, remaining, billed percent', () => {
    const b = invoicingBlock({
      invoices: [
        { invoice_number: 'INV-0088', display_number: 'INV-0088', status: 'paid', sent_date: '2025-06-20', closed_date: '2025-06-24', total: '3000.00' },
      ],
      scopeTotal: 12400,
      invoicedTotal: 3000,
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    const inv = stat(b, 'INV-0088');
    expect(inv.value).toBe('$3,000');
    expect(inv.sub).toBe('paid in 4 days');
    expect(inv.subTone).toBe('good');
    expect(stat(b, 'Remaining to bill').value).toBe('$9,400');
    const billed = stat(b, 'Billed');
    expect(billed.value).toBe('24%');
    expect(billed.sub).toBe('of $12,400');
  });

  it('draft invoices display but stay OUT of the billed math (header parity)', () => {
    // financials._invoiced excludes draft (and cancelled/superseded)
    // invoices, so the header's Invoiced figure and this block's Billed %
    // must agree: a draft's amount is not billed yet.
    const b = invoicingBlock({
      invoices: [
        { invoice_number: 'INV-0088', display_number: 'INV-0088', status: 'paid', sent_date: '2025-06-20', closed_date: '2025-06-24', total: '3000.00' },
        { invoice_number: 'INV-0092', display_number: 'INV-0092', status: 'draft', total: '9400.00' },
      ],
      scopeTotal: 12400,
      invoicedTotal: 3000, // the server's figure already excludes the draft
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    // The draft still shows as a row (it's real state)…
    const draft = stat(b, 'INV-0092');
    expect(draft.value).toBe('$9,400');
    expect(draft.sub).toBe('draft');
    // …but Billed/Remaining count only the sent-or-later invoices.
    expect(stat(b, 'Billed').value).toBe('24%');
    expect(stat(b, 'Remaining to bill').value).toBe('$9,400');
  });

  it('a draft invoice alone never reads fully-billed/frozen', () => {
    const b = invoicingBlock({
      invoices: [{ invoice_number: 'INV-0093', display_number: 'INV-0093', status: 'draft', total: '12400.00' }],
      scopeTotal: 12400,
      invoicedTotal: 0, // draft-only job: nothing invoiced yet, server-side
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    expect(stat(b, 'Billed').value).toBe('0%');
    expect(stat(b, 'Remaining to bill').value).toBe('$12,400');
  });

  it('active — unpaid aging clock', () => {
    const b = invoicingBlock({
      invoices: [
        { invoice_number: 'INV-0090', display_number: 'INV-0090', status: 'open', sent_date: '2025-06-20', total: '2000.00' },
      ],
      scopeTotal: 12400,
      now: '2025-07-09',
    });
    const inv = stat(b, 'INV-0090');
    expect(inv.sub).toBe('sent 19 days ago, unpaid');
    expect(inv.subTone).toBe('bad');
  });

  it('active — paid invoice with no closed_date reads just "paid", not aged-unpaid', () => {
    const b = invoicingBlock({
      invoices: [
        { invoice_number: 'INV-0091', display_number: 'INV-0091', status: 'paid', sent_date: '2025-06-20', total: '2000.00' },
      ],
      scopeTotal: 12400,
      now: '2025-07-09',
    });
    const inv = stat(b, 'INV-0091');
    expect(inv.sub).toBe('paid');
    expect(inv.subTone).toBe('good');
  });

  it('active — exactly 4 invoices does not collapse', () => {
    const invoices = [
      { invoice_number: 'INV-01', display_number: 'INV-01', status: 'paid', sent_date: '2025-01-01', closed_date: '2025-01-05', total: '100.00' },
      { invoice_number: 'INV-02', display_number: 'INV-02', status: 'paid', sent_date: '2025-02-01', closed_date: '2025-02-05', total: '100.00' },
      { invoice_number: 'INV-03', display_number: 'INV-03', status: 'open', sent_date: '2025-03-01', total: '100.00' },
      { invoice_number: 'INV-04', display_number: 'INV-04', status: 'open', sent_date: '2025-04-01', total: '100.00' },
    ];
    const b = invoicingBlock({ invoices, scopeTotal: 12400, now: '2025-07-09' });
    expect(stat(b, 'INV-01')).toBeTruthy();
    expect(stat(b, 'INV-02')).toBeTruthy();
    expect(stat(b, 'INV-03')).toBeTruthy();
    expect(stat(b, 'INV-04')).toBeTruthy();
    expect(b.stats.some((s) => s.label.includes('earlier invoices'))).toBe(false);
  });

  it('active — >4 invoices collapse oldest paid into one group', () => {
    const invoices = [
      { invoice_number: 'INV-01', display_number: 'INV-01', status: 'paid', sent_date: '2025-01-01', closed_date: '2025-01-05', total: '100.00' },
      { invoice_number: 'INV-02', display_number: 'INV-02', status: 'paid', sent_date: '2025-02-01', closed_date: '2025-02-05', total: '100.00' },
      { invoice_number: 'INV-03', display_number: 'INV-03', status: 'paid', sent_date: '2025-03-01', closed_date: '2025-03-05', total: '100.00' },
      { invoice_number: 'INV-04', display_number: 'INV-04', status: 'open', sent_date: '2025-04-01', total: '100.00' },
      { invoice_number: 'INV-05', display_number: 'INV-05', status: 'open', sent_date: '2025-05-01', total: '100.00' },
      { invoice_number: 'INV-06', display_number: 'INV-06', status: 'open', sent_date: '2025-06-01', total: '100.00' },
    ];
    const b = invoicingBlock({ invoices, scopeTotal: 12400, now: '2025-07-09' });
    // 6 live > 4 → collapse 3 oldest paid
    const group = stat(b, '3 earlier invoices');
    expect(group).toBeTruthy();
    expect(group.value).toBe('all paid');
    // the three oldest paid should NOT appear individually
    expect(stat(b, 'INV-01')).toBeUndefined();
    // the newer ones remain
    expect(stat(b, 'INV-06')).toBeTruthy();
  });

  it('marks deposit invoices in the invoicing block', () => {
    const b = invoicingBlock({
      invoices: [
        { display_number: 'INV-1042', status: 'open',
          sent_date: '2026-07-20T00:00:00Z', total: '5000',
          is_deposit: true },
      ],
      scopeTotal: 10000, invoicedTotal: 5000, now: '2026-07-25',
    });
    const s = b.stats.find((s) => s.label.includes('INV-1042'));
    expect(s.label).toContain('deposit');
  });

  it('does not append "· deposit" for a non-deposit invoice', () => {
    const b = invoicingBlock({
      invoices: [
        { display_number: 'INV-1043', status: 'open',
          sent_date: '2026-07-20T00:00:00Z', total: '5000',
          is_deposit: false },
      ],
      scopeTotal: 10000, invoicedTotal: 5000, now: '2026-07-25',
    });
    const s = b.stats.find((s) => s.label.includes('INV-1043'));
    expect(s.label).toBe('INV-1043');
  });

  it('frozen — fully billed and paid', () => {
    const b = invoicingBlock({
      invoices: [
        { invoice_number: 'INV-0088', display_number: 'INV-0088', status: 'paid', sent_date: '2025-06-20', closed_date: '2025-06-24', total: '12400.00' },
      ],
      scopeTotal: 12400,
      invoicedTotal: 12400,
      now: '2025-07-09',
    });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toContain('all paid');
  });
});

// ===========================================================================
// 6. DELIVERY
// ===========================================================================
describe('deliveryBlock', () => {
  it('dormant — deliverables defined, none ready', () => {
    const b = deliveryBlock({ shipments: [], deliverableCount: 3, job: { status: 'in_progress' }, now: '2025-07-09' });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('3 deliverables defined · none ready yet');
  });

  it('dormant — no deliverables', () => {
    const b = deliveryBlock({ shipments: [], deliverableCount: 0, job: { status: 'in_progress' }, now: '2025-07-09' });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('none ready yet');
  });

  it('active — prepared-not-picked-up past 3 working days is red', () => {
    const b = deliveryBlock({
      shipments: [{ sequence: 1, status: 'prepared', prepared_date: '2025-07-01' }],
      deliverableCount: 1,
      job: { status: 'in_progress' },
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    // 07-01 is a Tuesday; 8 days ago > 3 → red
    expect(b.clock).toEqual({ tone: 'bad', lines: ['ready since Tue, not picked up'] });
  });

  it('active — prepared exactly 3 calendar days ago is NOT red (boundary)', () => {
    const b = deliveryBlock({
      shipments: [{ sequence: 1, status: 'prepared', prepared_date: '2025-07-06' }],
      deliverableCount: 1,
      job: { status: 'in_progress' },
      now: '2025-07-09',
    });
    expect(b.clock.tone).toBe('neutral');
  });

  it('active — prepared exactly 4 calendar days ago IS red (boundary)', () => {
    const b = deliveryBlock({
      shipments: [{ sequence: 1, status: 'prepared', prepared_date: '2025-07-05' }],
      deliverableCount: 1,
      job: { status: 'in_progress' },
      now: '2025-07-09',
    });
    expect(b.clock.tone).toBe('bad');
  });

  it('active — prepared within threshold is not red', () => {
    const b = deliveryBlock({
      shipments: [{ sequence: 1, status: 'prepared', prepared_date: '2025-07-07' }],
      deliverableCount: 1,
      job: { status: 'in_progress' },
      now: '2025-07-09',
    });
    expect(b.state).toBe('active');
    expect(b.clock.tone).toBe('neutral');
    expect(b.clock.lines[0]).toMatch(/^ready since \w+, not picked up$/);
  });

  it('active — work complete with nothing shipped', () => {
    const b = deliveryBlock({ shipments: [], deliverableCount: 2, job: { status: 'work_complete' }, now: '2025-07-09' });
    expect(b.state).toBe('active');
    expect(b.clock.tone).toBe('warn');
    expect(b.clock.lines[0]).toBe('work complete, nothing shipped yet');
  });

  it('frozen — all picked up', () => {
    const b = deliveryBlock({
      shipments: [
        { status: 'picked_up', picked_up_date: '2025-07-10' },
        { status: 'picked_up', picked_up_date: '2025-07-15' },
        { status: 'picked_up', picked_up_date: '2025-07-18' },
      ],
      deliverableCount: 3,
      job: { status: 'completed' },
      now: '2025-07-20',
    });
    expect(b.state).toBe('frozen');
    expect(b.frozenText).toBe('3 shipments picked up · last 7/18');
  });
});

// ===========================================================================
// 6b. MATERIALS COVERAGE — the three-tone signal (2026-07-28).
//
// Buckets by whether a human must act: needed/needs-pricing → "needs
// ordering" (SHORT, red); ordered/awaiting-customer → "not yet arrived"
// (WAITING, amber); everything on hand → OK (green).
// ===========================================================================
const MAT = {
  inventory_item: 7, cost_source: 'entered', consumption_state: 'pending',
  quantity: '4.00', qty_on_hand: '0.00', po_line_item_id: null, po_number: null,
};
const needed = { ...MAT };
const needsPricing = { ...MAT, inventory_item: null, cost_source: null };
const ordered = { ...MAT, po_line_item_id: 3, qty_on_order: '4.00', po_number: 'PO-9' };
const awaitingCustomer = { ...MAT, cost_source: 'customer_supplied' };
const onHand = { ...MAT, qty_on_hand: '4.00' };
const consumed = { ...MAT, consumption_state: 'consumed' };

const coverage = (b) => b.stats.find((s) => s.label === 'Coverage');

describe('materialsBlock coverage', () => {
  const args = (materials, pos = []) => ({ jobId: 1, pos, materials, now: '2025-07-09' });

  it('no materials at all — the Coverage stat is omitted', () => {
    const b = materialsBlock(args([], [{ status: 'issued', po_number: 'PO-1', business_name: 'A' }]));
    expect(b.state).toBe('active');
    expect(coverage(b)).toBeUndefined();
  });

  it('all on hand → OK, green, no sub', () => {
    // OK only ever renders on an already-active block (an open PO here);
    // all-on-hand with no POs is dormant, asserted separately below.
    const b = materialsBlock(args([onHand, consumed], [{ status: 'issued', po_number: 'PO-1', business_name: 'A' }]));
    const c = coverage(b);
    expect(c.value).toBe('OK');
    expect(c.valueTone).toBe('good');
    expect(c.sub).toBeUndefined();
  });

  it('needed → SHORT with the needs-ordering count', () => {
    const c = coverage(materialsBlock(args([needed, onHand])));
    expect(c.value).toBe('SHORT');
    expect(c.valueTone).toBe('bad');
    expect(c.sub).toBe('1 needs ordering');
  });

  it('needs-pricing counts as needs-ordering, not as its own bucket', () => {
    const c = coverage(materialsBlock(args([needsPricing, needed])));
    expect(c.value).toBe('SHORT');
    expect(c.sub).toBe('2 need ordering');
  });

  it('ordered alone → WAITING, amber, not-yet-arrived', () => {
    const c = coverage(materialsBlock(args([ordered, onHand])));
    expect(c.value).toBe('WAITING');
    expect(c.valueTone).toBe('warn');
    expect(c.sub).toBe('1 not yet arrived');
  });

  it('awaiting-customer alone → WAITING (no PO involved)', () => {
    const c = coverage(materialsBlock(args([awaitingCustomer])));
    expect(c.value).toBe('WAITING');
    expect(c.sub).toBe('1 not yet arrived');
  });

  it('ordered + awaiting-customer share the not-yet-arrived bucket', () => {
    const c = coverage(materialsBlock(args([ordered, awaitingCustomer])));
    expect(c.value).toBe('WAITING');
    expect(c.sub).toBe('2 not yet arrived');
  });

  it('SHORT wins over WAITING, and the sub reports both buckets', () => {
    const c = coverage(materialsBlock(args([needed, ordered, awaitingCustomer, onHand])));
    expect(c.value).toBe('SHORT');
    expect(c.valueTone).toBe('bad');
    expect(c.sub).toBe('1 needs ordering · 2 not yet arrived');
  });

  it('a coverage alert re-heats the block even with no POs at all', () => {
    // Regression: awaiting-customer with no PO used to read dormant
    // ("nothing on order"), hiding the signal entirely.
    const b = materialsBlock(args([awaitingCustomer]));
    expect(b.state).toBe('active');
    expect(coverage(b).value).toBe('WAITING');
  });

  it('all-on-hand with no POs stays dormant — OK is not worth a card', () => {
    const b = materialsBlock(args([onHand]));
    expect(b.state).toBe('dormant');
  });

  it('frozen — received POs, nothing short', () => {
    const b = materialsBlock(args([onHand], [{ status: 'received_in_full' }]));
    expect(b.state).toBe('frozen');
  });
});

// ===========================================================================
// 7. BLOCK HREFS — the whole-card link target per block.
//
// Rule (2026-07-28 design): one named document → link to it; none or several
// → the block's section index. Every block returns an href in all three
// temperatures, so the card is never a dead end.
// ===========================================================================
const JOB_ID = 42;

describe('block hrefs', () => {
  describe('scopeBlock', () => {
    it('dormant — no estimate yet → the estimates section', () => {
      const b = scopeBlock({
        jobId: JOB_ID, estimates: [], changeOrders: [], deliverableCount: 0, now: '2025-07-09',
      });
      expect(b.state).toBe('dormant');
      expect(b.href).toBe('#/jobs/42/estimate');
    });

    it('active — targets the current estimate by id', () => {
      const b = scopeBlock({
        jobId: JOB_ID,
        estimates: [
          { estimate_id: 7, version: 1, status: 'superseded' },
          { estimate_id: 8, version: 2, status: 'open', sent_date: '2025-06-27' },
        ],
        changeOrders: [],
        deliverableCount: 0,
        now: '2025-07-09',
      });
      expect(b.state).toBe('active');
      expect(b.href).toBe('#/jobs/42/estimate/8');
    });

    it('active — a live change order wins over the estimate', () => {
      const b = scopeBlock({
        jobId: JOB_ID,
        estimates: [{ estimate_id: 8, version: 2, status: 'accepted', closed_date: '2025-07-01' }],
        changeOrders: [{ change_order_id: 3, change_order_number: 'CH-1', status: 'open', sent_date: '2025-07-05' }],
        deliverableCount: 0,
        now: '2025-07-09',
      });
      expect(b.state).toBe('active');
      expect(b.href).toBe('#/jobs/42/change-order/3');
    });

    it('frozen — still targets the current estimate', () => {
      const b = scopeBlock({
        jobId: JOB_ID,
        estimates: [{ estimate_id: 8, version: 2, status: 'accepted', closed_date: '2025-07-02', total: '100' }],
        changeOrders: [],
        deliverableCount: 0,
        now: '2025-07-09',
      });
      expect(b.state).toBe('frozen');
      expect(b.href).toBe('#/jobs/42/estimate/8');
    });

    it('falls back to the section index when the estimate carries no id', () => {
      const b = scopeBlock({
        jobId: JOB_ID,
        estimates: [{ version: 2, status: 'open', sent_date: '2025-06-27' }],
        changeOrders: [],
        deliverableCount: 0,
        now: '2025-07-09',
      });
      expect(b.href).toBe('#/jobs/42/estimate');
    });
  });

  describe('workBlock', () => {
    it('always the tasks section, whatever the temperature', () => {
      const base = { job: { job_id: JOB_ID, status: 'draft' }, overview: { work: {} } };
      expect(workBlock(base).href).toBe('#/jobs/42/tasks');
      expect(workBlock({ ...base, job: { job_id: JOB_ID, status: 'in_progress' } }).href)
        .toBe('#/jobs/42/tasks');
      expect(workBlock({
        job: { job_id: JOB_ID, status: 'completed' },
        overview: { work: { tasks_total: 3 }, spend: { labor_hours: 4 } },
      }).href).toBe('#/jobs/42/tasks');
    });
  });

  describe('materialsBlock', () => {
    it('always the job POs section — never the out-of-workspace PO detail page', () => {
      const onePO = materialsBlock({
        jobId: JOB_ID,
        pos: [{ po_id: 9, po_number: 'PO-1', status: 'issued', business_name: 'Acme' }],
        coverage: null,
        now: '2025-07-09',
      });
      expect(onePO.state).toBe('active');
      expect(onePO.href).toBe('#/jobs/42/pos');

      const dormant = materialsBlock({ jobId: JOB_ID, pos: [], coverage: null, now: '2025-07-09' });
      expect(dormant.state).toBe('dormant');
      expect(dormant.href).toBe('#/jobs/42/pos');
    });
  });

  describe('spendBlock', () => {
    it('the history section in every temperature (placeholder for Analysis)', () => {
      const dormant = spendBlock({ job: { job_id: JOB_ID, status: 'in_progress' }, overview: { spend: {} } });
      expect(dormant.state).toBe('dormant');
      expect(dormant.href).toBe('#/jobs/42/history');

      const active = spendBlock({
        job: { job_id: JOB_ID, status: 'in_progress' },
        overview: { spend: { total: 500, labor: 300, materials_bought: 200, labor_hours: 4 } },
      });
      expect(active.state).toBe('active');
      expect(active.href).toBe('#/jobs/42/history');
    });
  });

  describe('invoicingBlock', () => {
    const inv = (id, over = {}) => ({
      invoice_id: id, display_number: `INV-${id}`, status: 'sent',
      sent_date: '2025-07-01', total: '100', ...over,
    });

    it('exactly one live invoice → that invoice', () => {
      const b = invoicingBlock({
        jobId: JOB_ID, invoices: [inv(5)], scopeTotal: 1000, invoicedTotal: 100, now: '2025-07-09',
      });
      expect(b.href).toBe('#/jobs/42/invoice/5');
    });

    it('two or more live invoices → the section index', () => {
      const b = invoicingBlock({
        jobId: JOB_ID, invoices: [inv(5), inv(6)], scopeTotal: 1000, invoicedTotal: 200, now: '2025-07-09',
      });
      expect(b.href).toBe('#/jobs/42/invoice');
    });

    it('cancelled/superseded do not count toward the one-vs-many split', () => {
      const b = invoicingBlock({
        jobId: JOB_ID,
        invoices: [inv(5), inv(6, { status: 'cancelled' }), inv(7, { status: 'superseded' })],
        scopeTotal: 1000, invoicedTotal: 100, now: '2025-07-09',
      });
      expect(b.href).toBe('#/jobs/42/invoice/5');
    });

    it('dormant — no live invoices → the section index', () => {
      const b = invoicingBlock({
        jobId: JOB_ID, invoices: [], scopeTotal: 1000, invoicedTotal: 0, now: '2025-07-09',
      });
      expect(b.state).toBe('dormant');
      expect(b.href).toBe('#/jobs/42/invoice');
    });

    it('frozen — a single paid invoice still deep-links', () => {
      const b = invoicingBlock({
        jobId: JOB_ID,
        invoices: [inv(5, { status: 'paid', closed_date: '2025-07-05', total: '1000' })],
        scopeTotal: 1000, invoicedTotal: 1000, now: '2025-07-09',
      });
      expect(b.state).toBe('frozen');
      expect(b.href).toBe('#/jobs/42/invoice/5');
    });

    it('falls back to the section index when the lone invoice carries no id', () => {
      const b = invoicingBlock({
        jobId: JOB_ID,
        invoices: [{ display_number: 'INV-5', status: 'sent', sent_date: '2025-07-01', total: '100' }],
        scopeTotal: 1000, invoicedTotal: 100, now: '2025-07-09',
      });
      expect(b.href).toBe('#/jobs/42/invoice');
    });
  });

  describe('deliveryBlock', () => {
    it('always the shipments section', () => {
      const dormant = deliveryBlock({
        shipments: [], deliverableCount: 2, job: { job_id: JOB_ID, status: 'in_progress' }, now: '2025-07-09',
      });
      expect(dormant.state).toBe('dormant');
      expect(dormant.href).toBe('#/jobs/42/shipments');

      const frozen = deliveryBlock({
        shipments: [{ status: 'picked_up', picked_up_date: '2025-07-05' }],
        deliverableCount: 1, job: { job_id: JOB_ID, status: 'completed' }, now: '2025-07-09',
      });
      expect(frozen.state).toBe('frozen');
      expect(frozen.href).toBe('#/jobs/42/shipments');
    });
  });
});
