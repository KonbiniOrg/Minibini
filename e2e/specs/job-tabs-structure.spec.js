// Job page tab structure (frontend/README.md → "Job tab structure"). Every
// tab of the job page is one region labelled by its <h2>; the h2 sits in the
// region's <header> (TabHeader), and headings run from the job's <h1> down
// with no skipped levels. Read-only — no job is mutated.
import { expect, test } from '@playwright/test';
import { apiAs } from '../fixtures/api.js';
import { loadBackdrop } from '../fixtures/lookups.js';
import { personas } from '../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const asList = (r) => r?.results ?? r ?? [];

let job;
let changeOrder;

test.beforeAll(async () => {
  const jobs = await loadBackdrop();
  const api = await apiAs(personas.finjobs);
  try {
    // A job that shows real documents on the Estimates and Invoices tabs.
    for (const j of jobs) {
      const [ests, invs] = await Promise.all([
        api.get(`/api/estimates/?job=${j.job_id}`),
        api.get(`/api/invoices/?job=${j.job_id}`),
      ]);
      if (asList(ests).length && asList(invs).length && (j.tasks || []).length) { job = j; break; }
    }
    changeOrder = asList(await api.get('/api/change-orders/?page_size=1'))[0] ?? null;
  } finally {
    await api.dispose();
  }
});

// The page's headings in order, skipping open dialogs (their own outline).
async function headingLevels(page) {
  return page.evaluate(() => [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')]
    .filter((h) => !h.closest('[role="dialog"]') && h.getClientRects().length > 0)
    .map((h) => Number(h.tagName[1])));
}

async function expectTabStructure(page, title) {
  const region = page.getByRole('region', { name: title });
  await expect(region).toBeVisible();
  await expect(region.locator(':scope > header').getByRole('heading', { level: 2, name: title })).toBeAttached(); // visually hidden on tabs whose rail tab is the title
  await page.waitForLoadState('networkidle');
  const levels = await headingLevels(page);
  expect(levels[0], `levels ${levels}`).toBe(1);
  expect(levels.filter((l) => l === 1), `levels ${levels}`).toHaveLength(1);
  expect(levels.filter((l) => l === 2), `levels ${levels}`).toHaveLength(1);
  for (let i = 1; i < levels.length; i++) {
    expect(levels[i] - levels[i - 1], `levels ${levels}`).toBeLessThanOrEqual(1);
  }
}

const TABS = [
  { section: 'overview', title: 'Overview' },
  { section: 'estimate', title: /^Estimate: / },
  { section: 'tasks', title: 'Tasks' },
  { section: 'invoice', title: /^Invoice: / },
  { section: 'shipments', title: 'Shipments' },
  { section: 'pos', title: 'Purchase orders' },
  { section: 'emails', title: 'Emails' },
  { section: 'history', title: 'History' },
];

test('every job tab is a region headed by one h2, with no skipped heading levels', async ({ page }) => {
  test.skip(!job, 'seed gap: no job with an estimate, an invoice and tasks');
  await page.goto(`/#/jobs/${job.job_id}`);
  const rail = page.getByRole('navigation', { name: 'Job sections' });
  await expect(rail).toBeVisible();

  for (const { section, title } of TABS) {
    await test.step(`${section}: region labelled by its h2 → heading order h1 > h2 > h3`, async () => {
      await rail.locator(`.rail-link[data-section="${section}"]`).click();
      await expectTabStructure(page, title);
    });
  }
});

test('the change-order view (Estimates tab) follows the same structure', async ({ page }) => {
  test.skip(!changeOrder, 'seed gap: no change order');
  await page.goto(`/#/jobs/${changeOrder.job}/change-order/${changeOrder.change_order_id}`);
  await expectTabStructure(page, changeOrder.change_order_number || `CO #${changeOrder.change_order_id}`);
});
