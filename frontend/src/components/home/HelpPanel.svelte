<script>
  import { link } from 'svelte-spa-router';
  import { setupStatus } from '../../stores/setupStatus.js';
  import { setupHint } from '../../lib/setupHints.js';

  // The getting-started tutorial, converted to HTML with in-app links.
  // Source of truth: docs/designs/tutorial.md — keep the two in sync when
  // the tutorial changes (no markdown renderer in the SPA by design).

  // Setup checklist: unmet gates lead the help while setup is incomplete
  // and vanish once every area is available (same live predicates as the
  // sidebar; no stored flag).
  let unmetGates = $derived(
    $setupStatus.areas
      ? Object.entries($setupStatus.areas)
          .filter(([, a]) => !a.available)
          .map(([area, a]) => setupHint(area, a.message))
      : []
  );
</script>

<div class="help">

{#if unmetGates.length}
  <div class="setup-checklist">
    <h3>Finish setting up</h3>
    <p>Some areas are still locked until their configuration exists:</p>
    <ul>
      {#each unmetGates as hint}
        <li>{hint}</li>
      {/each}
    </ul>
    <p>Start in <a href="/settings" use:link>Settings</a> — connect
    QuickBooks Online there and pull your existing accounting setup,
    catalog, and customers to fill most of this in.</p>
  </div>
{/if}

<p>Minibini is a job shop management system. It tracks a job from the
first customer email through quoting, work on the floor, time tracking,
materials, purchasing, and invoicing (with payments synced from
QuickBooks Online). This tutorial walks the life of one job, and provides
a brief introduction to the other features of the software. It assumes
you know how a job shop runs but have never seen Minibini.</p>

<h3>Finding your way around</h3>

<p>Minibini runs in your browser. After you log in, the sidebar on the
left is the whole map: <strong>Home</strong> (your work, your shifts,
your expenses), <a href="/jobs/board" use:link><strong>Jobs</strong></a>
(the board), <a href="/schedule" use:link><strong>Schedule</strong></a>,
<a href="/activity" use:link><strong>Activity</strong></a> (who's working
right now), <a href="/contacts" use:link><strong>Contacts</strong></a>,
<a href="/email" use:link><strong>Email</strong></a>,
<a href="/purchase-orders" use:link><strong>Purchasing</strong></a>,
<a href="/catalog" use:link><strong>Catalog</strong></a> (inventory and
service items), and — depending on your permissions —
<a href="/invoices" use:link><strong>Invoices</strong></a>,
<a href="/expenses" use:link><strong>Expenses</strong></a>,
<a href="/users" use:link><strong>Users</strong></a>, and
<a href="/settings" use:link><strong>Settings</strong></a>. The sidebar
slides out from the hamburger menu on the top left of the screen.</p>

<p>The <a href="/jobs/board" use:link><strong>Job Board</strong></a> is
the overview of all shop work. It's a four-column kanban view of every
current job: <strong>Pipeline</strong> (being quoted), <strong>In
Progress</strong> (released to the floor, with a column per worker for
assigning individual tasks), <strong>Unpaid</strong> (work done, money
outstanding), and <strong>Closed</strong>. Click any card to open the
job detail.</p>

<h3>The main organizing concept</h3>

<p>A <strong>Job owns its work</strong>. Everything billable on a job is
one of three kinds of <em>atom</em>, all listed on the job's task-list
page:</p>

<ul>
  <li><strong>Task</strong> — a metered unit of work, like "CNC cut 12
    rectangles" or "draw 3d model of chair". Every task is priced by a
    <strong>rate scheme</strong>, either by elapsed time on the clock or
    by a quantity the worker enters (pieces, machine-minutes). Common
    tasks are kept in the
    <a href="/catalog/service-items" use:link>Service Items catalog</a>.</li>
  <li><strong>Material</strong> — a physical item, either picked from the
    <a href="/catalog" use:link>Materials catalog</a> (which reserves
    stock — see Materials below) or typed in freeform.</li>
  <li><strong>Fee</strong> — a fixed charge,
    <code>quantity × unit rate</code>. No timer, no stock; just a
    price.</li>
</ul>

<p>Estimates and invoices are <em>documents built from those same
atoms</em>. The estimate prices what you <strong>expect</strong> (a
task's estimated quantity); the invoice bills what <strong>actually
happened</strong> (logged time, entered counts, consumed materials). You
don't maintain the estimate and the invoice separately — they're both
linked to the same work.</p>

<h3>Estimating</h3>

<ol>
  <li><strong>Create the job.</strong> Start a new job from the button on
    the <a href="/jobs/board" use:link>board</a>'s header, or straight
    from a customer email on the <a href="/email" use:link>Email</a> page
    ("create job from email"). This also lets you create the contact and
    business if they're new. The job starts as a <strong>draft</strong>.</li>
  <li><strong>Add the work.</strong> On the job, add tasks, materials,
    and fees by hand, or pick from the
    <a href="/catalog/service-items" use:link>Service Items</a> or
    <a href="/catalog" use:link>Materials</a> catalogs. Give each task an
    estimated quantity and an estimated worker time (used for planning
    work). Also list the job's <strong>Deliverables</strong> — the
    customer-facing "what you get" list. These are considered part of the
    estimate, and are used to generate packing lists for completed
    work.</li>
  <li><strong>Build the estimate.</strong> Start an estimate and pull the
    job's atoms onto customer-facing line items (the estimate's
    <strong>Reconcile</strong> view shows the unclaimed atoms on one side
    and the line items on the other). You can assign one line per atom,
    or combine several atoms into one line the customer will understand,
    as when they request a per-unit price for pieces that take multiple
    steps to make. You can also type hand lines and percentage
    adjustments (rush fee, discount) directly.</li>
  <li><strong>Send it.</strong> Email the customer a PDF plus a
    <strong>portal link</strong> where they can accept, reject, or
    request changes — no login required on their end. The job moves to
    the <strong>submitted</strong> state. Estimates expire automatically
    after a configurable number of days. If the customer wants changes,
    the estimate can be revised — the old estimate is kept and marked
    superseded, and the new one sent to the customer with an incremented
    version number.</li>
  <li><strong>Acceptance.</strong> When the estimate is accepted the job
    becomes <strong>approved</strong>: hand-written lines crystallize
    into real Fee and Material atoms, and stock is earmarked for the job.
    A worker must review the job at this point and ensure the necessary
    materials and tasks are listed, and then release the job to the shop
    floor. Now it is <strong>in progress</strong>, and displayed in the
    In Progress area of the <a href="/jobs/board" use:link>Job Board</a>.</li>
</ol>

<p>After acceptance, any scope changes go through a <strong>Change
Order</strong>: put the job on hold (holding pauses new work but keeps
history), draft the CO, and send it to the customer through the same
portal. Accepting it updates the agreement and releases the hold
automatically.</p>

<h3>Doing the work</h3>

<p>Workers clock in from the top banner (a <strong>shift</strong>), then
hit <strong>Start</strong> on a task — theirs from the
<a href="/jobs/board" use:link>board</a> or
<a href="/schedule" use:link>schedule</a>, or any task they walk up to.
Each work session is recorded as a <strong>timeslip</strong> — who,
which task, start, and stop. One session at a time per person; starting
a second task closes the first. Starting the day's first task even
clocks you in automatically.</p>

<ul>
  <li>The first Start on a task moves it to <em>in progress</em> and
    consumes its materials from stock.</li>
  <li>Two people can work the same task ("join"), or one can take it
    over.</li>
  <li>Tasks can be <strong>blocked</strong> with a reason, and completed
    from any state.</li>
  <li>On count-based tasks, stopping or completing prompts "how
    many?"</li>
  <li>Forgot to log time? Add a historical entry — your own, within the
    last 30 hours; older or someone else's needs a time manager.</li>
  <li>You can work on a task assigned to someone else; workers can use
    their judgement on this</li>
</ul>

<p>The <a href="/jobs/board" use:link><strong>Job Board</strong></a>'s
in-progress tab is intended for reviewing work by several workers at
once, assigning work and prioritizing, with all current jobs and tasks
visible. Drag tasks to a worker's queue to assign or reorder them. You
can filter one or a few jobs' tasks by clicking on the job's chip in the
top row.</p>

<p>The <a href="/schedule" use:link><strong>Schedule</strong></a> page
lays each worker's assigned tasks on a calendar: dark bars are logged
work, light bars are the forecast from estimated times, split at a live
"now" line. Drag bars to reorder a worker's queue.</p>

<p>When every task on a job is complete or cancelled, the job advances
to <strong>work complete</strong> automatically.</p>

<h3>Catalog tasks, inventory, and purchasing</h3>

<p>The <a href="/catalog" use:link><strong>Catalog</strong></a> is the
shop's price list. It has three tabs:
<a href="/catalog/service-items" use:link><strong>Service Items</strong></a>
(the reusable task definitions),
<a href="/catalog" use:link><strong>Inventory</strong></a> (the items),
and <a href="/catalog/earmarks" use:link><strong>Earmarks</strong></a>
(every active stock reservation, shop-wide). Things to know about
inventory:</p>

<ul>
  <li>Each Material item shows <strong>on hand</strong>,
    <strong>earmarked</strong> (reserved by jobs),
    <strong>available</strong> (the difference), and <strong>on
    order</strong> (outstanding PO quantity). Putting a catalog material
    on a job earmarks stock the moment it's approved; starting the
    associated task consumes it.</li>
  <li>Sell price defaults from cost via a configurable <strong>markup
    percent</strong> at creation; after that, the stored price is what
    you edit.</li>
  <li>Items are never auto-hidden or deleted — a zero-stock item stays
    findable as history ("what did we pay last time"). Retire one by
    deactivating it; <strong>write off</strong> spoiled or wasted stock;
    <strong>merge</strong> accidental duplicates.</li>
  <li>A one-off material typed freeform on a job gets its own
    <code>LOT-</code> item behind the scenes once it's costed and
    purchased, so even one-time buys are tracked stock — and next year's
    search can find and reuse the lot.</li>
</ul>

<p>When there's not enough of a Material in inventory, a
<strong>Purchase Order</strong> button is shown in the job page. You can
also make one under
<a href="/purchase-orders" use:link>Purchasing</a>. PO lines attributed
to a job create that job's materials automatically. Email the PO to the
vendor as a PDF, receive it when the materials arrive to update QOH
value. The vendor's invoice (bill) is entered and paid in QuickBooks
Online — link the emailed bill to its PO from the Email page for the
paper trail.</p>

<h3>Finalizing a Job</h3>

<p>Once all Tasks are complete, the job moves into the <strong>work
complete</strong> stage. Now, or beforehand if it makes sense, create a
<strong>Shipment</strong> based on the Deliverables. You can configure
some or all of them as ready for pickup or delivery. Print a packing
list for the customer or courier's signature and mark the shipment
picked up when it's been picked up.</p>

<h3>Getting paid</h3>

<p>From a job that's work-complete (or anywhere along the way — deposits
and progress billing are fine), open an invoice and build it exactly the
way you built the estimate: its Reconcile view offers the job's billable
atoms — completed tasks at their actual quantities, consumed materials,
fees, loose expenses. Each atom can only ever be claimed by one invoice,
so double-billing is structurally impossible. The invoice is fully
editable by the user so if you don't want to charge according to the
actual work for whatever reason, you don't have to. And you can always
see what work was billed and what wasn't. Send the invoice (PDF email
again), and it's pushed to QuickBooks Online; Minibini polls QBO and
flips the invoice to partly-paid/paid as payments land. When all
invoices are resolved and all deliverables picked up, the job closes
itself as <strong>completed</strong>.</p>

<h3>Shop configuration (Settings)</h3>

<p>The <a href="/settings" use:link><strong>Settings</strong></a> page
(config permission required) is where the shop is tuned, in six
tabs:</p>

<ul>
  <li><strong>Accounting</strong> — the QuickBooks Online connection,
    accounting categories (every billable thing carries one; they drive
    taxability and QBO income mapping), which QBO payment accounts to
    poll, and any sync failures needing attention.</li>
  <li><strong>Setup</strong> — document numbering patterns (job, invoice,
    PO numbers), estimate expiry days, how long closed jobs linger on the
    board, and the list of measurement units the whole system validates
    against.</li>
  <li><strong>Pricing</strong> — the <strong>service price list</strong>
    (rate schemes: name, rate, billing algorithm, percent modifiers like
    "messy materials +10%") and the default material markup. One rule to
    internalize: once a service price has been used by real work it is
    <strong>frozen</strong> — changing the price means creating a new
    version, and existing work keeps billing at the rate it was sold
    at.</li>
  <li><strong>Schedule</strong> — the shop's default work week (days,
    hours, breaks) that drives the schedule's forecasting.</li>
  <li><strong>Email</strong> — subject/body templates for outbound
    estimates, invoices, and POs.</li>
  <li><strong>Business</strong> — your notification email, public site
    URL, and email domain.</li>
</ul>

<h3>Your own settings</h3>

<p>Everyone has a <a href="/profile" use:link><strong>Profile</strong></a>
tab on Home (click your name at the bottom of the sidebar) with account
info and a password change. The <strong>FULL / LITE</strong> toggle in
the sidebar switches view modes — lite pares pages down to the
essentials. Your personal <strong>work week</strong> — if it differs
from the shop's — is set on Home → Shifts, and the schedule forecasts
your queue inside those hours. You can review your recent Shifts and
time slips, make adjustments for recent errors or request adjustments
for older ones. You also have a list of assigned tasks, and you can
submit <strong>Expenses</strong> if you bought something for the shop on
your own dime.</p>

<p>Admins manage accounts, permissions, and other people's schedules on
the <a href="/users" use:link><strong>Users</strong></a> page.
Non-admins can see who's here now, what they're working on, and what
their schedules are.</p>

<h3>A few more things worth knowing</h3>

<ul>
  <li><strong>Everything is logged.</strong> Jobs, estimates, and
    invoices keep a full history — status changes, edits, and freeform
    notes anyone can add. Look for the History panel on a record's
    page.</li>
  <li><strong>Email is a workspace, not just an inbox.</strong> The
    <a href="/email" use:link>Email</a> page shows the shop's mailbox;
    from a message you can create a job (with the contact and business
    created along the way), or link it to an existing job or PO.
    Documents Minibini sends are recorded too and show up on the job's
    own Email panel.</li>
  <li><strong>Search</strong> (the box at the bottom of the sidebar)
    finds jobs, contacts, businesses, documents, and catalog items in one
    query.</li>
  <li><strong>Expenses</strong> — workers submit expenses from Home →
    Expenses (tied to a job or standalone), managers approve
    reimbursements, and job-tied expenses show up as billable atoms in
    invoicing.</li>
  <li><a href="/activity" use:link><strong>Activity</strong></a> shows
    who's clocked in and working on what right now, plus recent sessions
    and document events — the shop's live pulse.</li>
  <li><strong>Deliverables and shipments.</strong> The deliverables list
    you wrote at quoting time becomes the fulfillment checklist: prepare
    shipments, print packing lists, and record pick-ups. A job only
    closes when everything is picked up.</li>
</ul>

<h3>Who can do what</h3>

<p>Everyone logged in can see nearly everything, work tasks, and track
their own time and expenses. Four permission atoms gate the rest:
<strong>jobs</strong> (create estimates and contacts, job admin),
<strong>financials</strong> (create invoices and POs),
<strong>time</strong> (editing others' time), and
<strong>config</strong> (settings, templates, users). A job's
<strong>project manager</strong> gets job-level powers on that one job
without the global permission.</p>

<p>That's the loop: quote it, win it, work it, buy for it, bill it — one
job, one set of atoms, start to finish.</p>

</div>

<style>
  /* Prose width for readability, centered on the page; everything else
     inherits app styles. */
  .help {
    max-width: 46em;
    margin: 0 auto;
  }
  .help h3 {
    margin-top: 1.5em;
  }
  .setup-checklist {
    border: 1px solid #d97706;
    background: #fffbeb;
    border-radius: 6px;
    padding: 4px 16px 12px;
    margin-bottom: 20px;
  }
</style>
