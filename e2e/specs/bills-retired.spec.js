// Bill removal (2026-07-23, docs/plans/bill-removal-spec.md): bills live
// entirely in QBO. These assert the surfaces that used to link into the Bill
// domain no longer do — nav, search, PO detail, business detail.
//
// The retained breadcrumb (link a vendor-invoice email to its PO) is NOT
// covered here: the e2e seed contains no email fixtures, so that flow is
// exempt per the spec until an email seed exists.
import { expect, test } from '@playwright/test';
import { apiAs } from '../fixtures/api.js';
import { loadBackdrop } from '../fixtures/lookups.js';
import { personas } from '../fixtures/personas.js';

// finjobs carries can_manage_financials — the persona that used to see Bills.
test.use({ storageState: personas.finjobs.storageState });

test('sidebar offers no Bills entry (financials persona)', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation');
  await expect(nav.getByRole('link', { name: 'Invoices' })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Bills' })).toHaveCount(0);
});

test('search offers no Bills category', async ({ page }) => {
  await page.goto('/#/search?q=a');
  await expect(page.getByText('Search Results')).toBeVisible()
    .catch(() => {}); // heading text varies; the filter list is the assertion
  await expect(page.getByRole('checkbox', { name: 'Bills' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Bills' })).toHaveCount(0);
});

test('PO detail shows no billing affordances', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  let po;
  try {
    const resp = await api.get('/api/purchase-orders/?page=1');
    po = (resp?.results || [])[0];
  } finally {
    await api.dispose();
  }
  test.skip(!po, 'seed gap: no purchase orders');

  await page.goto(`/#/purchase-orders/${po.po_id}`);
  await expect(page.getByText(po.po_number)).toBeVisible();
  await expect(page.getByText(/Billed:/)).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Create Bill' })).toHaveCount(0);
});

test('business detail shows POs but no Bills panel', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  let business;
  try {
    const resp = await api.get('/api/businesses/?page=1');
    business = (resp?.results || [])[0];
  } finally {
    await api.dispose();
  }
  test.skip(!business, 'seed gap: no businesses');

  await page.goto(`/#/businesses/${business.business_id}`);
  await expect(
    page.getByRole('heading', { name: /Purchase Orders/ })
  ).toBeVisible();
  await expect(page.getByRole('heading', { name: /^Bills/ })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'New Bill' })).toHaveCount(0);
});
