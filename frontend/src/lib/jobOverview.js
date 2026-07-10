// jobOverview.js — the pure view-model for the job overview page's six
// lifecycle blocks (Scope → Work → Materials → Spend → Invoicing → Delivery).
//
// Every block rule, clock, temperature, and copy string lives HERE; the Svelte
// components (Task 5) are dumb renderers of what these functions return. The
// spec is docs/plans/2026-07-09-job-overview-redesign.md; copy strings come
// from the approved mockup overview-lifecycle-v4.html.
//
// Design contract (all functions are pure — no fetching, no Date.now()):
//   - `now` is always passed in (a Date or a 'YYYY-MM-DD' / ISO string). The
//     DUE countdown is NEVER computed here — it arrives pre-computed on the
//     overview endpoint payload (working_days_left). The response, pickup, and
//     invoice-latency clocks DO need day math; they use a tiny CALENDAR-day
//     diff helper (calendarDaysBetween) documented below. Client-side working
//     days are approximated by calendar days for the pickup clock (the shop
//     week envelope lives server-side; a 3-working-day pickup window is close
//     enough to 3 calendar days for a display signal, and the honest
//     working-day math is the endpoint's job for the one countdown that
//     matters — the job due date).
//
// Return shape (per block):
//   { state: 'active' | 'frozen' | 'dormant',
//     stats?:   [ StatItem ],       // active blocks
//     clock?:   { tone, lines: [string] },  // active blocks, optional
//     frozenText?: string,          // frozen blocks
//     dormantText?: string }        // dormant blocks
//
// StatItem = { label, value, unit?, valueTone?, pill?: {text, tone},
//              sub?, subTone?, bar? }
//   - tones: 'good' | 'warn' | 'bad' | 'neutral' (components map to CSS)
//   - pill.tone: the raw status string (e.g. 'open', 'accepted') for styling
//   - bar: 0..100 progress percentage (Work's progress bar)
// NOTE for Task 5: `valueTone`, `pill`, and `bar` extend the brief's minimal
// {label,value,unit,sub,subTone} — they carry the mockup's value coloring,
// status pills, and progress bar so the components stay pure renderers.

// ---------------------------------------------------------------------------
// Threshold constants. Eventual home is Configuration (spec) — do NOT build
// config UI this pass.
// ---------------------------------------------------------------------------
export const RESPONSE_CLOCK_DAYS = 7;        // customer response clock red at ≥ this
export const DUE_PRESSURE_WORKING_DAYS = 5;  // due countdown amber within this
export const PICKUP_CLOCK_WORKING_DAYS = 3;  // pickup clock red past this (calendar approx)
export const INVOICE_ROW_MAX = 4;            // > this many invoice rows → collapse oldest paid

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// --- date helpers (calendar-day math, timezone-stable via UTC parts) --------

// Extract {y, m, d} from a Date or an ISO/'YYYY-MM-DD' string. Strings are read
// by their literal date portion (no local-tz shift); Dates use local parts.
function dayParts(x) {
  if (x == null) return null;
  if (x instanceof Date) {
    return { y: x.getFullYear(), m: x.getMonth() + 1, d: x.getDate() };
  }
  const datePortion = String(x).split('T')[0];
  const [y, m, d] = datePortion.split('-').map(Number);
  if (!y || !m || !d) return null;
  return { y, m, d };
}

function utcMs(parts) {
  return Date.UTC(parts.y, parts.m - 1, parts.d);
}

// Whole calendar days from `from` to `to` (to − from). Positive when `to` is
// later. Used by every clock that isn't the endpoint's due countdown.
function calendarDaysBetween(from, to) {
  const a = dayParts(from);
  const b = dayParts(to);
  if (!a || !b) return null;
  return Math.round((utcMs(b) - utcMs(a)) / 86400000);
}

function fmtMonthDay(iso) {
  const p = dayParts(iso);
  if (!p) return '—';
  return `${MONTHS[p.m - 1]} ${p.d}`;
}

function fmtSlash(iso) {
  const p = dayParts(iso);
  if (!p) return '—';
  return `${p.m}/${p.d}`;
}

function fmtWeekday(iso) {
  const p = dayParts(iso);
  if (!p) return '';
  return DOW[new Date(utcMs(p)).getUTCDay()];
}

// --- number helpers ---------------------------------------------------------

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

// "$12,400" — whole dollars, thousands grouped, cents dropped (mockup style).
function fmtMoney(v) {
  return '$' + Math.round(num(v)).toLocaleString('en-US');
}

// "64" from "64.0", "41.5" from "41.5" — drop a trailing .0.
function fmtHours(v) {
  const n = num(v);
  return Number.isInteger(n) ? String(n) : String(n);
}

function pct(part, whole) {
  if (!whole) return 0;
  return Math.round((num(part) / num(whole)) * 100);
}

// ===========================================================================
// 1. SCOPE — estimate versions, change orders, deliverables.
// ===========================================================================
export function scopeBlock({ estimates = [], changeOrders = [], deliverableCount = 0, now }) {
  // Dormant: no estimate exists at all.
  if (!estimates.length) {
    let text = 'no estimate yet';
    if (deliverableCount > 0) text += ` · ${deliverableCount} deliverables defined`;
    return { state: 'dormant', dormantText: text };
  }

  const current = currentEstimate(estimates);
  const openCO = changeOrders.find((c) => c.status === 'draft' || c.status === 'open');
  const estActive = current.status === 'draft' || current.status === 'open';

  // Active — the current estimate is still draft/open (a revision re-heats
  // likewise, since a new draft is the current estimate).
  if (estActive) {
    return scopeActiveEstimate(current, estimates, changeOrders, deliverableCount, now);
  }

  // Active — the estimate has settled but a draft/open change order re-heats
  // the block and runs the customer-response clock on the CO's sent date.
  if (openCO) {
    return scopeActiveChangeOrder(current, openCO, deliverableCount, now);
  }

  // Frozen — estimate terminal, no live CO.
  return scopeFrozen(current, changeOrders, deliverableCount);
}

function currentEstimate(estimates) {
  const live = estimates.filter((e) => e.status !== 'superseded');
  const pool = live.length ? live : estimates;
  return pool.reduce((a, b) => (num(b.version) >= num(a.version) ? b : a));
}

function scopeActiveEstimate(current, estimates, changeOrders, deliverableCount, now) {
  const superseded = estimates
    .filter((e) => e.status === 'superseded')
    .sort((a, b) => num(a.version) - num(b.version));
  const estStat = {
    label: 'Estimate',
    value: `v${current.version}`,
    pill: { text: String(current.status).toUpperCase(), tone: current.status },
  };
  if (superseded.length) {
    estStat.sub = `${superseded.map((e) => `v${e.version}`).join(', ')} superseded`;
  }
  const stats = [
    estStat,
    { label: 'Total', value: current.total != null ? fmtMoney(current.total) : '—' },
    { label: 'Sent', value: current.sent_date ? fmtMonthDay(current.sent_date) : '—' },
    { label: 'Change orders', value: changeOrders.length ? String(changeOrders.length) : '—' },
    { label: 'Deliverables', value: String(deliverableCount) },
  ];
  const block = { state: 'active', stats };
  const clock = responseClock(current.sent_date, current.status, now);
  if (clock) block.clock = clock;
  return block;
}

function scopeActiveChangeOrder(current, co, deliverableCount, now) {
  const coStat = {
    label: 'Change order',
    value: co.change_order_number,
    pill: { text: String(co.status).toUpperCase(), tone: co.status },
  };
  if (co.total != null) coStat.sub = `+${fmtMoney(co.total)}`;
  const stats = [
    coStat,
    {
      label: 'Estimate',
      value: `v${current.version}`,
      pill: { text: String(current.status).toUpperCase(), tone: current.status },
    },
    { label: 'Total', value: current.total != null ? fmtMoney(current.total) : '—' },
    { label: 'Deliverables', value: String(deliverableCount) },
  ];
  const block = { state: 'active', stats };
  const clock = responseClock(co.sent_date, co.status, now);
  if (clock) block.clock = clock;
  return block;
}

function scopeFrozen(current, changeOrders, deliverableCount) {
  const acceptedCOs = changeOrders.filter((c) => c.status === 'accepted');
  const parts = [];
  if (current.status === 'accepted') {
    const total = num(current.total) + acceptedCOs.reduce((s, c) => s + num(c.total), 0);
    parts.push(fmtMoney(total));
    parts.push(`v${current.version} accepted ${fmtSlash(current.closed_date)}`);
  } else {
    // rejected / expired — lead with the version fact.
    parts.push(`v${current.version} ${current.status} ${fmtSlash(current.closed_date)}`);
  }
  for (const co of acceptedCOs) {
    parts.push(`${co.change_order_number} accepted ${fmtSlash(co.closed_date)}`);
  }
  if (deliverableCount > 0) parts.push(`${deliverableCount} deliverables`);
  return { state: 'frozen', frozenText: parts.join(' · ') };
}

// Customer-response clock: quiet under RESPONSE_CLOCK_DAYS, red at/above it.
// Only runs on a document that is open AND has been sent.
function responseClock(sentDate, status, now) {
  if (status !== 'open' || !sentDate) return null;
  const days = calendarDaysBetween(sentDate, now);
  if (days == null) return null;
  return {
    tone: days >= RESPONSE_CLOCK_DAYS ? 'bad' : 'neutral',
    lines: [`No customer response in ${days} days`],
  };
}

// ===========================================================================
// 2. WORK — progress, tasks, due, who's working now.
// ===========================================================================
const PRE_APPROVAL_JOB_STATUSES = ['draft', 'submitted'];
const WORK_DONE_JOB_STATUSES = ['work_complete', 'completed'];

export function workBlock({ job, overview, tasksPlanned = 0 }) {
  const work = (overview && overview.work) || {};
  const status = job && job.status;

  // Dormant — job not yet approved.
  if (PRE_APPROVAL_JOB_STATUSES.includes(status)) {
    const planned = tasksPlanned || num(work.tasks_total);
    const text = planned > 0
      ? `${planned} tasks planned · starts when the scope is accepted`
      : 'starts when the scope is accepted';
    return { state: 'dormant', dormantText: text };
  }

  // Frozen — work complete.
  if (WORK_DONE_JOB_STATUSES.includes(status)) {
    const hours = fmtHours((overview.spend && overview.spend.labor_hours) || 0);
    return { state: 'frozen', frozenText: `${num(work.tasks_total)} tasks · ${hours}h logged` };
  }

  // Active — approved / in_progress.
  const stats = [progressStat(work)];
  const tasksStat = {
    label: 'Tasks',
    value: String(num(work.tasks_complete)),
    unit: ` / ${num(work.tasks_total)}`,
  };
  if (num(work.tasks_blocked) > 0) {
    tasksStat.sub = `${num(work.tasks_blocked)} BLOCKED`;
    tasksStat.subTone = 'bad';
  }
  stats.push(tasksStat);

  const dueStat = dueStatOf(overview.due);
  if (dueStat) stats.push(dueStat);

  const block = { state: 'active', stats };
  const workingNow = work.working_now || [];
  if (workingNow.length) {
    block.clock = {
      tone: 'good',
      lines: workingNow.map((w) => `● ${w.worker_name} working now — ${w.task_name}`),
    };
  }
  return block;
}

function progressStat(work) {
  const estTotal = num(work.est_time_total_hours);
  if (estTotal > 0) {
    const estDone = num(work.est_time_complete_hours);
    const p = pct(estDone, estTotal);
    return {
      label: 'Progress · by estimated time',
      value: `${p}%`,
      unit: `${fmtHours(estDone)}h of ${fmtHours(estTotal)}h`,
      bar: p,
    };
  }
  // Fallback: task-count percent when estimates are absent.
  const total = num(work.tasks_total);
  const done = num(work.tasks_complete);
  const p = pct(done, total);
  return {
    label: 'Progress · by task count',
    value: `${p}%`,
    unit: `${done} of ${total}`,
    bar: p,
  };
}

// Due stat is omitted entirely when the job has no due date (endpoint sends
// due: null). working_days_left is the endpoint's honest working-day count.
function dueStatOf(due) {
  if (!due || !due.date) return null;
  const left = due.working_days_left;
  const s = { label: 'Due', value: fmtSlash(due.date) };
  if (left < 0) {
    s.sub = `overdue by ${Math.abs(left)} working days`;
    s.subTone = 'bad';
    s.valueTone = 'bad';
  } else if (left <= DUE_PRESSURE_WORKING_DAYS) {
    s.sub = `${left} working days left`;
    s.subTone = 'warn';
    s.valueTone = 'warn';
  } else {
    s.sub = `${left} working days left`;
    s.subTone = 'neutral';
    s.valueTone = 'neutral';
  }
  return s;
}

// ===========================================================================
// 3. MATERIALS — POs touching the job + coverage signal.
// materialsBlock takes no `now` (the brief signature) — PO due dates are shown
// but not toned, since pressure needs a clock reference the block isn't given.
// ===========================================================================
const OPEN_PO_STATUSES = ['draft', 'issued', 'partly_received'];

export function materialsBlock({ pos = [], coverage = null }) {
  const openPOs = pos.filter((p) => OPEN_PO_STATUSES.includes(p.status));
  const receivedPOs = pos.filter((p) => p.status === 'received_in_full');
  const coverageShort = coverage && coverage.tone === 'bad';

  // Dormant — no POs and no shortfall.
  if (!pos.length && !coverageShort) {
    return { state: 'dormant', dormantText: 'nothing on order' };
  }

  // Frozen — POs exist, none open, coverage not short.
  if (!openPOs.length && !coverageShort) {
    const n = receivedPOs.length;
    return { state: 'frozen', frozenText: `${n} ${n === 1 ? 'PO' : 'POs'}, all received` };
  }

  // Active — any open PO or coverage short.
  const stats = [];
  for (const po of openPOs) {
    const sent = po.issued_date || po.created_date;
    stats.push({
      label: 'On order',
      value: po.po_number,
      sub: `${po.business_name}${sent ? ` · sent ${fmtSlash(sent)}` : ''}`,
    });
    if (po.requested_date) {
      stats.push({ label: 'Due', value: fmtSlash(po.requested_date) });
    }
  }
  if (receivedPOs.length) {
    stats.push({
      label: 'Received',
      value: String(receivedPOs.length),
      unit: receivedPOs.length === 1 ? ' PO' : ' POs',
    });
  }
  if (coverage) {
    const cov = { label: 'Coverage', value: coverage.label, valueTone: coverage.tone };
    if (coverage.sub) cov.sub = coverage.sub;
    stats.push(cov);
  }
  return { state: 'active', stats };
}

// ===========================================================================
// 4. SPEND — labor / materials / total, against scope.
// ===========================================================================
const TERMINAL_JOB_STATUSES = ['completed', 'rejected', 'cancelled'];

export function spendBlock({ job, overview, scopeTotal = 0 }) {
  const spend = (overview && overview.spend) || {};
  const total = num(spend.total);
  const status = job && job.status;

  // Dormant — nothing spent.
  if (total <= 0) {
    return { state: 'dormant', dormantText: 'nothing spent yet' };
  }

  const labor = fmtMoney(spend.labor);
  const materials = fmtMoney(spend.materials_bought);
  const totalStr = fmtMoney(total);

  // Frozen — terminal job: the same three figures as settled facts.
  if (TERMINAL_JOB_STATUSES.includes(status)) {
    return {
      state: 'frozen',
      frozenText: `${labor} labor · ${materials} materials · ${totalStr} total`,
    };
  }

  // Active — anything spent, job not terminal.
  const totalStat = { label: 'Total spent', value: totalStr };
  if (scopeTotal > 0) {
    totalStat.sub = `${pct(total, scopeTotal)}% of the ${fmtMoney(scopeTotal)} scope`;
  } else {
    totalStat.sub = 'spent so far';
  }
  return {
    state: 'active',
    stats: [
      { label: 'Labor', value: labor, sub: `${fmtHours(spend.labor_hours)} hours` },
      { label: 'Materials', value: materials, sub: 'bought so far' },
      totalStat,
    ],
  };
}

// ===========================================================================
// 5. INVOICING — per-invoice latency clocks, remaining, billed %.
// ===========================================================================
const INVOICE_DEAD_STATUSES = ['cancelled', 'superseded'];

export function invoicingBlock({ invoices = [], scopeTotal = 0, now }) {
  const live = invoices.filter((i) => !INVOICE_DEAD_STATUSES.includes(i.status));

  // Dormant — no live invoices.
  if (!live.length) {
    return { state: 'dormant', dormantText: 'none yet' };
  }

  const billed = live.reduce((s, i) => s + invoiceTotal(i), 0);
  const remaining = Math.max(scopeTotal - billed, 0);
  const allPaid = live.every((i) => i.status === 'paid');
  const fullyBilled = scopeTotal > 0 && billed >= scopeTotal;

  // Frozen — fully billed and paid.
  if (allPaid && fullyBilled) {
    return {
      state: 'frozen',
      frozenText: `${live.length} ${live.length === 1 ? 'invoice' : 'invoices'}, all paid · ${fmtMoney(billed)} billed`,
    };
  }

  // Active. Order invoices chronologically (oldest first) so a "Deposit" reads
  // before a "Final".
  const chrono = [...live].sort(
    (a, b) => utcMs(dayParts(invoiceDate(a)) || { y: 0, m: 1, d: 1 }) -
              utcMs(dayParts(invoiceDate(b)) || { y: 0, m: 1, d: 1 })
  );

  const stats = [];
  let individual = chrono;
  if (chrono.length > INVOICE_ROW_MAX) {
    // Collapse the oldest run of PAID invoices so total rows fit.
    const toCollapse = chrono.length - (INVOICE_ROW_MAX - 1);
    const collapsed = [];
    for (const inv of chrono) {
      if (collapsed.length >= toCollapse || inv.status !== 'paid') break;
      collapsed.push(inv);
    }
    if (collapsed.length) {
      stats.push({ label: `${collapsed.length} earlier invoices`, value: 'all paid', valueTone: 'good' });
      individual = chrono.slice(collapsed.length);
    }
  }

  for (const inv of individual) {
    stats.push(invoiceStat(inv, now));
  }

  stats.push({ label: 'Remaining to bill', value: fmtMoney(remaining) });
  stats.push({
    label: 'Billed',
    value: `${pct(billed, scopeTotal)}%`,
    sub: `of ${fmtMoney(scopeTotal)}`,
  });

  return { state: 'active', stats };
}

function invoiceStat(inv, now) {
  const s = { label: inv.invoice_number, value: fmtMoney(invoiceTotal(inv)) };
  if (inv.status === 'paid' && inv.sent_date && inv.closed_date) {
    const days = calendarDaysBetween(inv.sent_date, inv.closed_date);
    s.sub = `paid in ${days} days`;
    s.subTone = 'good';
  } else if (inv.sent_date && inv.status !== 'draft') {
    const days = calendarDaysBetween(inv.sent_date, now);
    s.sub = `sent ${days} days ago, unpaid`;
    s.subTone = 'bad';
  }
  return s;
}

function invoiceDate(inv) {
  return inv.sent_date || inv.created_date;
}

// Invoice money source. Task 6: the invoice list serializer exposes no total
// field, and line items carry only qty/price (adjustment & percentage lines
// make qty*price wrong), so an authoritative `total` must be wired onto the
// invoice payload. Consume it here; 0 until wired.
function invoiceTotal(inv) {
  return num(inv.total);
}

// ===========================================================================
// 6. DELIVERY — shipments + deliverables.
// ===========================================================================
export function deliveryBlock({ shipments = [], deliverableCount = 0, job, now }) {
  const prepared = shipments.filter((s) => s.status === 'prepared');
  const pickedUp = shipments.filter((s) => s.status === 'picked_up');
  const status = job && job.status;
  const workDone = WORK_DONE_JOB_STATUSES.includes(status);

  // Frozen — everything picked up.
  if (shipments.length && !prepared.length) {
    const last = pickedUp
      .map((s) => s.picked_up_date)
      .filter(Boolean)
      .sort((a, b) => utcMs(dayParts(a)) - utcMs(dayParts(b)))
      .pop();
    return {
      state: 'frozen',
      frozenText: `${pickedUp.length} ${pickedUp.length === 1 ? 'shipment' : 'shipments'} picked up · last ${fmtSlash(last)}`,
    };
  }

  // Active — a prepared shipment awaits pickup, or work is done and nothing
  // has shipped.
  if (prepared.length) {
    const stats = [{
      label: 'Shipments',
      value: String(pickedUp.length),
      unit: ` / ${shipments.length}`,
    }];
    const lines = [];
    let tone = 'neutral';
    for (const sh of prepared) {
      const days = calendarDaysBetween(sh.prepared_date, now);
      if (days != null && days > PICKUP_CLOCK_WORKING_DAYS) tone = 'bad';
      lines.push(`ready since ${fmtWeekday(sh.prepared_date)}, not picked up`);
    }
    return { state: 'active', stats, clock: { tone, lines } };
  }
  if (workDone && !shipments.length) {
    return {
      state: 'active',
      stats: [{ label: 'Shipments', value: '0', unit: ` / ${deliverableCount}` }],
      clock: { tone: 'warn', lines: ['work complete, nothing shipped yet'] },
    };
  }

  // Dormant — nothing prepared yet.
  const text = deliverableCount > 0
    ? `${deliverableCount} deliverables defined · none ready yet`
    : 'none ready yet';
  return { state: 'dormant', dormantText: text };
}
