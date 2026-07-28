// docs/ui-flows/Job-Overview.md §8 — Block links (2026-07-28).
// Each of the six lifecycle blocks is one link covering the whole card: a
// named document when the block names exactly one, otherwise the section
// index. Read-only — no job is mutated, so no `used` claiming is needed.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { findJobWithEstimate, loadBackdrop } from '../../fixtures/lookups.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

let jobs;

test.beforeAll(async () => {
  jobs = await loadBackdrop();
});

// A block by its title. Filtering on `.summary-block-title` rather than the
// card's text matters: "scope" also appears inside Spend's "% of the $X scope"
// sub-line, so a hasText match on the card would be ambiguous.
const block = (page, title) =>
  page.locator('.summary-block').filter({
    has: page.locator('.summary-block-title', { hasText: new RegExp(`^${title}$`) }),
  });

const TITLES = ['Scope', 'Work', 'Materials', 'Spend', 'Invoicing', 'Delivery'];

test('§8 Block links', async ({ page }) => {
  const hit = await findJobWithEstimate(jobs, { jobStatus: 'in_progress', estimateStatus: 'accepted' })
    ?? await findJobWithEstimate(jobs, { jobStatus: 'approved', estimateStatus: 'accepted' });
  test.skip(!hit, 'seed gap: no in-production job with an accepted estimate');
  const jobId = hit.job.job_id;

  await page.goto(`/#/jobs/${jobId}`);
  await expect(block(page, 'Scope')).toBeVisible();

  await test.step('every block is an anchor with a job-scoped href', async () => {
    for (const title of TITLES) {
      const card = block(page, title);
      await expect(card).toHaveCount(1);
      // The card itself is the <a> — not a wrapper around one.
      await expect(card).toHaveJSProperty('tagName', 'A');
      await expect(card).toHaveAttribute('href', new RegExp(`^#/jobs/${jobId}/`));
    }
  });

  await test.step('no block nests a control inside the card', async () => {
    for (const title of TITLES) {
      await expect(block(page, title).locator('a, button, input, select, textarea')).toHaveCount(0);
    }
  });

  await test.step('fixed destinations', async () => {
    await expect(block(page, 'Work')).toHaveAttribute('href', `#/jobs/${jobId}/tasks`);
    // Always the job's POs section, never the out-of-workspace PO detail page.
    await expect(block(page, 'Materials')).toHaveAttribute('href', `#/jobs/${jobId}/pos`);
    await expect(block(page, 'Spend')).toHaveAttribute('href', `#/jobs/${jobId}/history`);
    await expect(block(page, 'Delivery')).toHaveAttribute('href', `#/jobs/${jobId}/shipments`);
  });

  await test.step('Scope deep-links to a specific document', async () => {
    // Estimate or change order depending on whether a CO is live on this job;
    // either way it must name a document, not land on the section index.
    await expect(block(page, 'Scope')).toHaveAttribute(
      'href', new RegExp(`^#/jobs/${jobId}/(estimate|change-order)/\\d+$`),
    );
  });

  await test.step('Invoicing: one live invoice deep-links, several do not', async () => {
    const api = await apiAs(personas.finjobs);
    const resp = await api.get(`/api/invoices/?job=${jobId}`);
    await api.dispose();
    const live = (resp?.results || resp || []).filter(
      (i) => !['cancelled', 'superseded'].includes(i.status));

    if (live.length === 1) {
      await expect(block(page, 'Invoicing')).toHaveAttribute(
        'href', `#/jobs/${jobId}/invoice/${live[0].invoice_id}`);
    } else {
      await expect(block(page, 'Invoicing')).toHaveAttribute('href', `#/jobs/${jobId}/invoice`);
    }
  });

  await test.step('clicking the card body navigates (section-index case)', async () => {
    // Click the Work block's title, not its edge — proves the whole card is
    // the target, not just a corner affordance.
    await block(page, 'Work').locator('.summary-block-title').click();
    await expect(page).toHaveURL(new RegExp(`#/jobs/${jobId}/tasks$`));
  });

  await test.step('clicking the card body navigates (deep-link case)', async () => {
    await page.goto(`/#/jobs/${jobId}`);
    const href = await block(page, 'Scope').getAttribute('href');
    await block(page, 'Scope').locator('.summary-block-title').click();
    await expect(page).toHaveURL(new RegExp(`${href.replace('#', '')}$`));
  });
});
