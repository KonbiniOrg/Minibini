// docs/ui-flows/Deposits.md §1 — creating a deposit invoice via the
// invoice panel's "Add Deposit Invoice" / "Make this a deposit invoice"
// button + modal (Task 21, 2026-07 — replaces the picker's "Add Deposit"
// entry; refined 2026-07-26 into three states — no draft / draft with no
// lines / draft with lines), and the DEPOSIT pill it earns on the invoices
// list. QBO is unreachable in e2e, so this covers only the draft-side
// creation UI — the seeded PAID deposit (deposit-credit.spec.js) covers the
// paid/claimed side.
//
// This spec drives Start Invoice first (rather than the one-step "no draft"
// path, already covered by Vitest) specifically to exercise state 2's
// browser-only behavior: the relabel to "Make this a deposit invoice" once
// an empty draft exists, and the in-place reload (no hash navigation) when
// the deposit line lands on the draft already being viewed.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-deposit-${Date.now().toString(36)}`;

// State 2 needs "Start Invoice" to land on a genuinely EMPTY draft — but a
// fresh invoice now auto-seeds from the job's agreement by default (Task 4:
// InvoiceWizardService.open_for_job, seed=True), so a billable job that
// carries an accepted estimate would already have lines the moment the
// draft exists, and "Make this a deposit invoice" (draftHasLines-gated)
// would never appear. No seeded job is both billable/invoice-less AND
// estimate-less, so this builds one via the hand-approval path (same
// precedent as add-line-and-work-authoring/estimate-gate-and-live-
// picker.spec.js's quoting-phase-gate job): draft -> submitted -> approved,
// no estimate ever created, so compose_agreement (and therefore seeding)
// is guaranteed empty.
async function makeInvoicelessEstimatelessJob() {
  const api = await apiAs(personas.finjobs);
  try {
    const contact = (await api.get('/api/contacts/?page_size=1')).results[0];
    const job = await api.post('/api/jobs/', {
      name: `${stamp} job`, contact: contact.contact_id,
    });
    await api.patch(`/api/jobs/${job.job_id}/`, { status: 'submitted' });
    return await api.patch(`/api/jobs/${job.job_id}/`, { status: 'approved' });
  } finally {
    await api.dispose();
  }
}

test('§1 Creating a deposit invoice: states 1→2→3', async ({ page }) => {
  const job = await makeInvoicelessEstimatelessJob();

  await test.step('State 1 (no draft): Add Deposit Invoice is offered next to Start Invoice', async () => {
    await page.goto(`/#/jobs/${job.job_id}/invoice`);
    await expect(page.getByRole('button', { name: 'Start Invoice' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add Deposit Invoice' })).toBeEnabled();
  });

  await test.step('Start Invoice creates an empty draft', async () => {
    await page.getByRole('button', { name: 'Start Invoice' }).click();
    await expect(page.getByText(/^Invoice: /)).toBeVisible();
  });

  await test.step('State 2 (draft, no lines): the action relabels to "Make this a deposit invoice"', async () => {
    await expect(page.getByRole('button', { name: 'Make this a deposit invoice' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Add Deposit Invoice' })).toHaveCount(0);
  });

  const hashBeforeCreate = () => new URL(page.url()).hash;
  let hashBefore;

  await test.step('Modal: enter amount 2500, Create', async () => {
    hashBefore = hashBeforeCreate();
    await page.getByRole('button', { name: 'Make this a deposit invoice' }).click();
    const modal = page.getByRole('dialog', { name: 'Add Deposit Invoice' });
    await expect(modal.getByRole('heading', { name: 'Add Deposit Invoice' })).toBeVisible();
    await modal.getByLabel('Amount').fill('2500');
    await modal.getByRole('button', { name: 'Create' }).click();
    await expect(modal).toBeHidden();
  });

  await test.step('The line appears in place — no navigation (same draft was already open)', async () => {
    expect(hashBeforeCreate()).toBe(hashBefore);
    const row = page.locator('tr', { hasText: `Deposit on ${job.job_number}` });
    await expect(row).toBeVisible();
    // The merged Edit view's line row has no Category-name column (only a
    // Backing column) — assert the deposit BackingChip instead of the old
    // lines table's category-name text.
    await expect(row.locator('.backing-chip')).toHaveText('deposit');
    await expect(row).toContainText('$2500.00');
  });

  await test.step('The all-deposit draft withholds the Uncovered work pool (RM 2026-08-09)', async () => {
    await expect(page.getByRole('heading', { name: 'Unbilled work' })).toHaveCount(0);
  });

  await test.step('State 3 (draft has lines): the deposit action is suppressed entirely', async () => {
    await expect(page.getByRole('button', { name: 'Make this a deposit invoice' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Add Deposit Invoice' })).toHaveCount(0);
  });

  await test.step('The invoices list shows the DEPOSIT pill', async () => {
    await page.goto('/#/invoices');
    await page.getByLabel('Status:').selectOption('draft');
    const listRow = page.locator('tr', {
      has: page.getByRole('link', { name: job.job_number, exact: true }),
    });
    await expect(listRow.locator('.deposit-pill')).toHaveText('DEPOSIT');
  });

  await test.step('Cleanup: discard the draft', async () => {
    const api = await apiAs(personas.finjobs);
    try {
      const resp = await api.get(`/api/invoices/?job=${job.job_id}`);
      const list = resp?.results || resp || [];
      for (const inv of list.filter((i) => i.status === 'draft')) {
        await api.del(`/api/invoices/${inv.invoice_id}/?confirm=true`);
      }
    } finally {
      await api.dispose();
    }
  });
});
