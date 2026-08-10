// docs/ui-flows/Change-Orders.md §5 — the empty-CO content gate: a CO with
// no changes at all is refused; a deliverables-only CO IS sendable
// (RM 2026-07-20).
//
// EMAIL EXEMPTION: minibini/settings.py hardcodes the real SMTP backend
// (smtp.gmail.com) and the e2e harness sets no email override, so actually
// DELIVERING the customer email is not e2e-able here — a UI send of a
// sendable CO would open a live SMTP session (and, with credentials in the
// developer's env, mail a real address). The refusal half runs through the
// send page because its validation fires BEFORE any email work; the
// sendable half is proven at the same shared gate via mark-open
// (ChangeOrder.clean's draft-exit guard — the invariant home the send path
// copies, per apps/estimates/change_order_service.has_sendable_changes).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { findJobWithEstimate, loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;
let jobs;
const used = new Set();

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

test('§5 Send gate — truly empty refused; deliverables-only sendable', async ({ page }) => {
  // noChangeOrders: this test creates the job's first CO — a candidate that
  // already carries one (e.g. from another spec earlier in the same run)
  // would fail change-order creation, which requires no existing CO.
  const hit = await findJobWithEstimate(jobs, {
    jobStatus: 'in_progress', estimateStatus: 'accepted', used, noChangeOrders: true,
  });
  test.skip(!hit, 'seed gap: no in_progress job with an accepted estimate and no change order yet');
  const { job } = hit;

  // API-side setup: the CO room entry flow is §1's spec; this one is about
  // the send gate, so hold + create go through fixtures/api.js.
  const api = await apiAs(personas.finjobs);
  await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: 'e2e: send-gate CO' });
  const co = await api.post('/api/change-orders/', { job: job.job_id });

  await test.step('Send page: a CO with no changes at all is refused', async () => {
    await page.goto(`/#/change-orders/${co.change_order_id}/send`);
    // Never let a test send race toward a real address: overwrite the
    // prefilled recipient. (The refusal fires server-side before any email.)
    await page.getByLabel('To *').fill('e2e-refusal@example.invalid');
    // The send form confirms before submitting (irreversible action).
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Send Email' }).click();
    await expect(page.getByText(/Cannot send an empty change order/)).toBeVisible();
    expect((await api.get(`/api/change-orders/${co.change_order_id}/`)).status).toBe('draft');
  });

  await test.step('Mark-open refuses the same empty CO (shared draft-exit gate)', async () => {
    const resp = await api.patchRaw(`/api/change-orders/${co.change_order_id}/`, { status: 'open' });
    expect(resp.status()).toBe(400);
    expect(await resp.text()).toContain('empty change order');
  });

  await test.step('A deliverables-only change makes the CO sendable', async () => {
    await api.post(`/api/jobs/${job.job_id}/deliverables/`, {
      description: `${stamp} scope correction`, qty_ordered: '1', units: 'ea',
    });
    // Same gate, now satisfied by the deliverables half alone — no line items.
    const opened = await api.patch(`/api/change-orders/${co.change_order_id}/`, { status: 'open' });
    expect(opened.status).toBe('open');
    expect(opened.sent_date).toBeTruthy();
    // And the CO page reflects it: the open-CO toolbar replaces the draft one.
    await page.goto(`/#/jobs/${job.job_id}/change-order/${co.change_order_id}`);
    await expect(page.getByRole('button', { name: 'Record Accepted' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Resend to customer' })).toBeVisible();
  });

  await api.dispose();
});
