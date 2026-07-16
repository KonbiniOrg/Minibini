// docs/ui-flows/Expenses.md §1 — Creating expenses: the shapes.
// One test() per numbered flow section, one test.step() per [ ] checkbox,
// same wording as the doc (docs/designs/e2e-testing.md §2).
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

// Financials persona: §1's company-paid branch needs the payment-accounts
// dropdown, which only loads for can_manage_financials. (The worker side of
// the picker is §2's first checkbox — a worker-persona spec. Note: a worker
// navigating straight to #/expenses currently gets the whole page blanked by
// the financials-only outstanding-summary 403 — flagged as app drift.)
test.use({ storageState: personas.financials.storageState });

// Unique run marker so list assertions can't collide with seed rows or with
// earlier PW_KEEP_DB reruns.
const stamp = `e2e-${Date.now().toString(36)}`;

// The anchor job comes from the seed — this flow tests making *expenses*,
// so only the expenses are created; everything they reference is backdrop
// (docs/designs/e2e-testing.md §2 layering rule).
let job;

test.beforeAll(async () => {
  const api = await apiAs(personas.financials);
  job = (await api.get('/api/jobs/?open=true&page_size=1')).results[0];
  await api.dispose();
});

// ---- form helpers -----------------------------------------------------

async function openNewExpenseForm(page) {
  await page.goto('/#/expenses');
  await page.getByRole('button', { name: '+ New expense' }).click();
}

async function fillBasics(page, { amount, description }) {
  await page.getByLabel('Amount').fill(String(amount));
  await page.getByLabel('Description', { exact: false }).first().fill(description);
  await page.getByLabel('Category').selectOption({ label: 'Service' });
}

async function pickSubjectJob(page) {
  await page.getByPlaceholder('Search jobs…').fill(job.job_number);
  await page.getByRole('listbox')
    .getByRole('button', { name: job.job_number }).click();
}

async function submitAndFindRow(page, description) {
  await page.getByRole('button', { name: 'Submit expense' }).click();
  const row = page.getByRole('row', { name: new RegExp(description) });
  await expect(row).toBeVisible();
  return row;
}

// Column order in the expenses table:
// Date · Who · Description · Job · Task · Category · Amount · Paid · Status · Actions
const COL = { job: 3, paid: 7 };

async function jobMaterials() {
  const api = await apiAs(personas.financials);
  const detail = await api.get(`/api/jobs/${job.job_id}/`);
  await api.dispose();
  return detail.materials;
}

// ---- §1 ----------------------------------------------------------------

test('§1 Creating expenses — the shapes', async ({ page }) => {
  await test.step('Overhead (no job): clear the Job field → save; blank Job in the list', async () => {
    await openNewExpenseForm(page);
    await fillBasics(page, { amount: 12.34, description: `${stamp} parking` });
    // The Job field starts blank — leave it that way.
    const row = await submitAndFindRow(page, `${stamp} parking`);
    await expect(row.getByRole('cell').nth(COL.job)).toHaveText('—');
  });

  await test.step('Job service cost (no item): pick a Job, add no item, save → anchored to the job', async () => {
    await openNewExpenseForm(page);
    await fillBasics(page, { amount: 45, description: `${stamp} third-party shipping` });
    await pickSubjectJob(page);
    const row = await submitAndFindRow(page, `${stamp} third-party shipping`);
    await expect(row.getByRole('link', { name: job.job_number })).toBeVisible();
  });

  await test.step('Cost item — freeform: qty + unit cost → creates a consumable material at that unit cost', async () => {
    await openNewExpenseForm(page);
    await fillBasics(page, { amount: 66, description: `${stamp} lumber run` });
    await pickSubjectJob(page);
    await page.getByRole('button', { name: '+ Add a purchased item' }).click();
    // Leave the price-list item unpicked — freeform.
    await page.getByLabel('Item description').fill(`${stamp} poplar boards`);
    await page.getByLabel('Quantity').fill('2');
    await page.getByLabel('Unit cost').fill('30');
    await submitAndFindRow(page, `${stamp} lumber run`);
    // The material's unit cost is the $30 that was typed — NOT amount ÷ qty
    // ($33); the $6 gap between amount and goods is unbudgeted tax/shipping.
    const material = (await jobMaterials())
      .find((m) => m.description === `${stamp} poplar boards`);
    expect(material).toBeTruthy();
    expect(Number(material.quantity)).toBe(2);
    expect(Number(material.unit_cost)).toBe(30);
  });

  await test.step('No existing-material list: only create-new — no option to pick/link an existing material', async () => {
    await openNewExpenseForm(page);
    await pickSubjectJob(page);
    await page.getByRole('button', { name: '+ Add a purchased item' }).click();
    // The purchased-item fieldset offers exactly one picker — the price-list
    // item type-ahead — and nothing that links an existing material.
    await expect(page.getByPlaceholder('Search inventory items…')).toBeVisible();
    await expect(page.getByText(/existing material/i)).toHaveCount(0);
    await page.getByRole('button', { name: 'Cancel' }).click();
  });

  await test.step('Personal → requires purchased-by per §2 (financials: picker shown, defaults to self)', async () => {
    await openNewExpenseForm(page);
    await expect(page.getByLabel('Paid by')).toHaveValue('personal');
    await expect(page.getByLabel('Purchased by')).toBeVisible();
    // Drift, do not assert yet: the picker's option list is EMPTY for a
    // financials-only persona. getPaymentAccounts() reads config-gated
    // /api/settings/ and THROWS on the 403, aborting loadDropdowns before
    // the workers fetch — and even reached, /api/users/ is admin-gated
    // (the lightweight /api/auth/users/ dropdown is the IsAuthenticated
    // one). So "defaults to the current user" (§2) only holds for
    // superusers today. Belongs to §2's spec once fixed.
    await page.getByRole('button', { name: 'Cancel' }).click();
    // The rows created above all default to the current user as purchaser.
    const row = page.getByRole('row', { name: new RegExp(`${stamp} parking`) });
    await expect(row.getByRole('link', { name: personas.financials.displayName }))
      .toBeVisible();
  });

});

// BLOCKED by app/doc drift: the company-paid branch is unreachable for the
// financials persona. The Paid-by dropdown's accounts come from
// getPaymentAccounts() → /api/settings/, which is can_manage_config-gated
// and throws on the 403 — so despite the seed's configured
// qbo_payment_accounts, a financials-only user sees no company option (and
// the same throw aborts loadDropdowns, emptying the Purchased-by picker).
// Decide the intended read access (e.g. expose payment accounts to
// financials, or a non-config read endpoint), then un-fixme:
// select 'Checking' → reference field appears → save → row shows 'company'
// and (QBO not connected in the seed, deliberately) a sync-failed badge.
test.fixme('§1 Company → requires a payment account; reference field appears; QBO push (doc/app drift)', async () => {});

// BLOCKED by app/doc drift, found while writing this spec. Two §1 checkboxes
// depend on the retired inventoried/non-inventoried distinction
// (InventoryItem.is_inventoried was removed in inventory migration 0028):
//
// - Backend: ExpenseService.submit treats EVERY inventory-item-linked
//   new_material as a stock receipt (`if pli: stock_pli, stock_qty = ...`) —
//   the doc's "cost item — non-inventoried PLI" shape no longer exists.
// - Frontend: MaterialPicker still keys isStock off `pli.is_inventoried`
//   (always undefined now), so it shows the cost-item fields for every item
//   and the typed unit cost is silently discarded while the backend receives
//   stock. Verified live: an item-linked expense saved with no material and
//   a QOH bump.
//
// Un-fixme (and update Expenses.md §1) once the intended split is decided —
// e.g. MaterialPicker switches to the stock-purchase UI whenever an item is
// picked, and the doc drops the non-inventoried cost-item shape.
test.fixme('§1 Purchased item linked to a catalog item — stock receipt vs cost item (doc/app drift)', async () => {});
