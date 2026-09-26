// Add Line modal editable descriptions (RM 2026-09-20, mirrors the
// Add-Task-time money override pattern — estimates-and-prices.md §3.6c): a
// catalog pick (service or inventory) now shows the same Description input
// the freeform branch always had, prefilled with the server's own
// derivation; an untouched add still derives server-side, but an edit is
// sent as an explicit override and wins. This is the one real-browser,
// real-API round trip for a catalog (inventory) pick — the fine-grained
// matrix (both catalog paths x override/absent/blank, CO + invoice lenses)
// is already exercised at the Django test level
// (tests/test_deferred_service_crystallization.py,
// tests/test_catalog_line_item_adds.py, tests/test_invoice_line_from_service.py,
// tests/test_change_order_acceptance.py) and the component level
// (frontend/tests/components/EstimateAddLineForm.test.js and its CO/invoice
// siblings) against a mocked API.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-catdesc-${Date.now().toString(36)}`;

test('catalog pick prefills the description; editing it overrides the catalog derivation on the saved line', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
  const cats = await api.get('/api/accounting-categories/');
  const cat = (cats.results || cats).find((c) => c.is_active !== false && !c.is_deposit);

  const job = await api.post('/api/jobs/', {
    name: `${stamp} job`, contact: contact.contact_id,
  });
  const estimate = await api.post('/api/estimates/', { job: job.job_id });

  const itemCode = `${stamp}-BOLT`;
  const catalogDescription = `${stamp} Steel bolt (catalog)`;
  const item = await api.post('/api/inventory/', {
    code: itemCode, description: catalogDescription, units: 'ea',
    purchase_price: '1.00', selling_price: '2.50', accounting_category: cat.id,
  });

  const editedDescription = `${stamp} Zinc-plated bolt, rushed`;

  await test.step('Add line → catalog inventory pick: description prefills from the PLI, untouched, then edited', async () => {
    await page.goto(`/#/jobs/${job.job_id}/estimate/${estimate.estimate_id}`);
    await page.getByRole('button', { name: 'Add line' }).click();
    const picker = page.getByRole('dialog');
    await picker.getByPlaceholder(/search/i).fill(itemCode);
    await picker.getByRole('listbox').getByRole('button', { name: new RegExp(itemCode) }).click();

    const form = page.getByRole('dialog');
    await expect(form.getByLabel(/Description/)).toHaveValue(catalogDescription);

    await form.getByLabel(/Description/).fill(editedDescription);
    await form.getByLabel(/Quantity/).fill('4');
    await form.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  await test.step('The line renders the edited description, never the catalog one', async () => {
    await expect(
      page.locator('table.line-items-table tr').filter({ hasText: editedDescription })
    ).toBeVisible();
    await expect(
      page.locator('table.line-items-table tr').filter({ hasText: catalogDescription })
    ).toHaveCount(0);
  });

  await test.step('The server persisted the override, and price/qty/AC still came from the PLI', async () => {
    const detail = await api.get(`/api/estimates/${estimate.estimate_id}/`);
    const line = detail.line_items.find((li) => li.inventory_item === item.inventory_item_id);
    expect(line.description).toBe(editedDescription);
    expect(Number(line.price)).toBe(2.5);
    expect(Number(line.qty)).toBe(4);
    expect(line.accounting_category).toBe(cat.id);
  });

  await api.dispose();
});
