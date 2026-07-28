// docs/ui-flows/Job-Overview.md §3 — the Materials block's three-tone Coverage
// signal (2026-07-28). Materials are bucketed by whether a human must act:
// needed/needs-pricing → SHORT, ordered/awaiting-customer → WAITING, all on
// hand → OK.
//
// API-side setup: the seed carries no provisional (unpriced) and no
// customer-supplied materials — every seeded material is item-backed with an
// entered cost — so both shapes are created here. The flow under test is the
// Coverage rendering, not the material's own authoring path (e2e-testing.md §2
// layering rule).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

// Create a fresh job carrying exactly one material of the requested shape, so
// nothing else on the job can influence the signal.
async function jobWithMaterial(label, material) {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const cats = await api.get('/api/accounting-categories/');
  const category = (cats.results || cats)[0];
  const job = await api.post('/api/jobs/', {
    name: `${stamp} ${label}`, contact: contact.contact_id,
  });
  await api.post(`/api/jobs/${job.job_id}/materials/`, {
    ...material, accounting_category: category.accounting_category_id ?? category.id,
  });
  await api.dispose();
  return job.job_id;
}

// The Coverage stat inside the Materials block.
function coverage(page) {
  return page
    .locator('.summary-block')
    .filter({ has: page.locator('.summary-block-title', { hasText: /^Materials$/ }) })
    .locator('.stat')
    .filter({ has: page.locator('.stat-label', { hasText: /^Coverage$/ }) });
}

test('§3 an unpriced material drives Coverage to SHORT', async ({ page }) => {
  // The regression this guards: a provisional (inventory_item null) material
  // used to be ignored by the Coverage count, so a job whose materials were
  // all unpriced showed a clean green OK. No cost and no catalog item is
  // exactly what the material modal sends when the price is left blank.
  const jobId = await jobWithMaterial('short', {
    description: 'unpriced stock', quantity: '4', units: 'each',
  });

  await page.goto(`/#/jobs/${jobId}`);
  const stat = coverage(page);
  await expect(stat).toHaveCount(1);
  await expect(stat.locator('.stat-value')).toHaveText(/SHORT/);
  await expect(stat.locator('.stat-value')).toHaveClass(/clock-bad/);
  await expect(stat.locator('.stat-sub')).toHaveText(/1 needs ordering/);
});

test('§3 material awaited from the customer reads WAITING, not SHORT', async ({ page }) => {
  // Customer-supplied is born established at a locked $0 with an empty lot:
  // short of stock, but nobody has to order anything — you wait. It also has
  // no PO, so this doubles as the regression for the block staying ACTIVE on a
  // coverage alert alone (it used to read dormant "nothing on order", hiding
  // the signal entirely).
  const jobId = await jobWithMaterial('waiting', {
    description: 'customer trim', quantity: '4', units: 'each', customer_supplied: true,
  });

  await page.goto(`/#/jobs/${jobId}`);
  const stat = coverage(page);
  await expect(stat).toHaveCount(1);
  await expect(stat.locator('.stat-value')).toHaveText(/WAITING/);
  await expect(stat.locator('.stat-value')).toHaveClass(/clock-warn/);
  await expect(stat.locator('.stat-sub')).toHaveText(/1 not yet arrived/);
});
