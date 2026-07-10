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
    const b = materialsBlock({ pos: [], coverage: null });
    expect(b.state).toBe('dormant');
    expect(b.dormantText).toBe('nothing on order');
  });

  it('active — open PO line + received + coverage', () => {
    const b = materialsBlock({
      pos: [
        { po_number: 'PO-0031', status: 'issued', business_name: 'Plywood Supply Co', issued_date: '2025-06-28', requested_date: '2025-07-10' },
        { po_number: 'PO-0027', status: 'received_in_full', received_date: '2025-06-30' },
      ],
      coverage: { label: 'OK', tone: 'good', sub: 'stock + this order' },
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
    expect(cov.sub).toBe('stock + this order');
  });

  it('active — coverage short with no open PO', () => {
    const b = materialsBlock({
      pos: [{ po_number: 'PO-0027', status: 'received_in_full', received_date: '2025-06-30' }],
      coverage: { label: 'SHORT', tone: 'bad', sub: 'need 4 more' },
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
        { invoice_number: 'INV-0088', status: 'paid', sent_date: '2025-06-20', closed_date: '2025-06-24', total: '3000.00' },
      ],
      scopeTotal: 12400,
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

  it('active — unpaid aging clock', () => {
    const b = invoicingBlock({
      invoices: [
        { invoice_number: 'INV-0090', status: 'open', sent_date: '2025-06-20', total: '2000.00' },
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
        { invoice_number: 'INV-0091', status: 'paid', sent_date: '2025-06-20', total: '2000.00' },
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
      { invoice_number: 'INV-01', status: 'paid', sent_date: '2025-01-01', closed_date: '2025-01-05', total: '100.00' },
      { invoice_number: 'INV-02', status: 'paid', sent_date: '2025-02-01', closed_date: '2025-02-05', total: '100.00' },
      { invoice_number: 'INV-03', status: 'open', sent_date: '2025-03-01', total: '100.00' },
      { invoice_number: 'INV-04', status: 'open', sent_date: '2025-04-01', total: '100.00' },
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
      { invoice_number: 'INV-01', status: 'paid', sent_date: '2025-01-01', closed_date: '2025-01-05', total: '100.00' },
      { invoice_number: 'INV-02', status: 'paid', sent_date: '2025-02-01', closed_date: '2025-02-05', total: '100.00' },
      { invoice_number: 'INV-03', status: 'paid', sent_date: '2025-03-01', closed_date: '2025-03-05', total: '100.00' },
      { invoice_number: 'INV-04', status: 'open', sent_date: '2025-04-01', total: '100.00' },
      { invoice_number: 'INV-05', status: 'open', sent_date: '2025-05-01', total: '100.00' },
      { invoice_number: 'INV-06', status: 'open', sent_date: '2025-06-01', total: '100.00' },
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

  it('frozen — fully billed and paid', () => {
    const b = invoicingBlock({
      invoices: [
        { invoice_number: 'INV-0088', status: 'paid', sent_date: '2025-06-20', closed_date: '2025-06-24', total: '12400.00' },
      ],
      scopeTotal: 12400,
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
