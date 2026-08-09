// docs/ui-flows/Invoice-Seeding-and-Send.md §4 — the "struck from agreement"
// badge on an uncovered-work row (2026-07-20): an atom whose claiming
// estimate line an ACCEPTED change order removed/replaced, while the atom
// itself stayed live (complete task, consumed material), is badged in the
// invoice's uncovered-work pool so the biller chooses consciously. Untouched
// atoms carry no badge.
// (The cancelled-task suppression — "cancelled — work done" wins over the
// struck badge — is a one-flag render rule covered by the unit tests:
// frontend/tests/components/wizards/WizardAtomRow.test.js and
// tests/test_co_struck_badge.py; not re-raced here.)
//
// UPDATED for the better-fees skeleton phase: the old "Show Billables"
// wizard toggle is retired (Task 13) — the invoice's Edit view always shows
// an "Uncovered work" section inline. A fresh draft also now auto-seeds
// from the agreement by default (Task 4: InvoiceWizardService.open_for_job,
// seed=True) — the CO stripped the "strike" line from the current
// agreement, so its task lands in Uncovered work (still badged); the
// "control" line is untouched, so it seeds straight onto the invoice as a
// normal claimed line instead of appearing in the pool at all.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

let jobs;

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

// Shape: an in_progress job with an accepted estimate holding TWO distinct
// lines whose claim rows all point at COMPLETE tasks — one line to strike
// (its task gets the badge; being complete, crystallization leaves it alone)
// and one untouched control line (its task must NOT be badged). All-complete
// sources keep acceptance from cancelling anything, so no shapes churn for
// later specs.
async function findStruckShape() {
  const api = await apiAs(personas.finjobs);
  try {
    for (const job of jobs.filter((j) => j.status === 'in_progress' && !j.on_hold)) {
      const resp = await api.get(`/api/estimates/?job=${job.job_id}`);
      const est = (resp?.results || resp || []).find((e) => e.status === 'accepted');
      if (!est) continue;
      const detail = await api.get(`/api/estimates/${est.estimate_id}/`);
      const taskById = new Map((job.tasks || []).map((t) => [t.task_id, t]));
      const completeTaskLines = [];
      for (const li of detail.line_items || []) {
        const sources = li.sources || [];
        if (sources.length === 0) continue;
        const lineTasks = sources.map(
          (s) => (s.source_type === 'task' ? taskById.get(s.source_pk) : null));
        if (lineTasks.every((t) => t && t.status === 'complete')) {
          completeTaskLines.push({ line: li, task: lineTasks[0] });
        }
      }
      if (completeTaskLines.length >= 2) {
        const [strike, control] = completeTaskLines;
        if (strike.task.name !== control.task.name) {
          return { job, strike, control };
        }
      }
    }
    return null;
  } finally {
    await api.dispose();
  }
}

test('§4 "Struck from agreement" badge in Show Billables', async ({ page }) => {
  const hit = await findStruckShape();
  test.skip(!hit, 'seed gap: no in_progress job with two accepted-estimate lines claiming complete tasks');
  const { job, strike, control } = hit;

  // API-side setup (fixtures/api.js): the CO room entry and send flows have
  // their own specs — this one is about the badge, so the accepted-CO state
  // is built directly: hold → CO → remove line → open → accepted.
  const api = await apiAs(personas.finjobs);
  await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: 'e2e: struck-badge CO' });
  const co = await api.post('/api/change-orders/', { job: job.job_id });
  await api.post(`/api/change-orders/${co.change_order_id}/line-items/`, {
    action: 'remove', target_line_item: strike.line.line_item_id,
  });
  await api.patch(`/api/change-orders/${co.change_order_id}/`, { status: 'open' });
  await api.patch(`/api/change-orders/${co.change_order_id}/`, { status: 'accepted' });

  await test.step('Acceptance left the complete task alone (and cleared the hold)', async () => {
    const fresh = await api.get(`/api/jobs/${job.job_id}/`);
    expect(fresh.on_hold).toBe(false);
    const task = fresh.tasks.find((t) => t.task_id === strike.task.task_id);
    expect(task.status).toBe('complete');
  });

  // A draft invoice hosts the doc — auto-seeded from the (now CO-amended)
  // agreement by default, so the untouched "control" line arrives already
  // claimed and the struck line does not.
  const invoice = await api.post('/api/invoices/', { job: job.job_id });
  await api.dispose();

  await test.step('Uncovered work: the struck atom row wears the badge', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice/${invoice.invoice_id}`);
    await expect(page.getByRole('heading', { name: 'Uncovered work' })).toBeVisible();
    const strikeRow = page.locator('.uncovered-work-section tr').filter({ hasText: strike.task.name });
    await expect(strikeRow).toBeVisible();
    await expect(strikeRow.getByText('struck from agreement')).toBeVisible();
  });

  await test.step('The untouched line seeded straight onto the invoice carries no badge', async () => {
    // Still part of the agreement, so it was auto-seeded as a real claimed
    // line — it never enters the uncovered-work pool at all, and a normal
    // line row (or its nested AtomChildRow — the seeded line may bundle
    // more than one task, so the task's own name is only guaranteed to
    // show up on its AtomChildRow, not necessarily the parent's own
    // description) has no "struck" concept to badge.
    await expect(page.locator('.uncovered-work-section tr').filter({ hasText: control.task.name }))
      .toHaveCount(0);
    const controlRows = page.locator('table.line-items-table tr').filter({ hasText: control.task.name });
    await expect(controlRows.first()).toBeVisible();
    await expect(controlRows.getByText('struck from agreement')).toHaveCount(0);
  });
});
