// e2e/specs/purchasing/po-order-flow.spec.js
// docs/ui-flows/Purchasing.md §11 — the Order modal (PO order flow spec
// docs/plans/2026-10-14-po-order-flow.md). Seed facts used: item 30
// BBPLY.5 has vendor history (newest: Royal Plywood, PO0012); material 6 on
// job 19 (08008) uses it and is pending/unlinked; the seed has no draft POs;
// email 10 is an unlinked vendor invoice with no matching contact.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-pof-${Date.now().toString(36)}`;

async function dismissOverlay(page) {
  const btn = page.getByRole('button', { name: 'Dismiss message' });
  if (await btn.count()) await btn.first().click();
}

test('§11 order a material with history → Create PO → order again → Add to the draft', async ({ page }) => {
  test.setTimeout(120_000);
  const api = await apiAs(personas.finjobs);
  const job = await api.get('/api/jobs/19/');
  const material = job.materials.find((m) => m.material_id === 6);
  test.skip(!material || material.po_line_item_id != null, 'seed gap: material 6 on job 19 is not pending/unlinked');
  const history = await api.get('/api/inventory/30/vendor-history/');
  test.skip(!history.vendors.length, 'seed gap: BBPLY.5 has no vendor history');
  const newest = history.vendors[0];
  let poUrl, poId, poNumber;
  try {

    await test.step('Vendor from history: Order on the material row preselects the newest vendor', async () => {
      await page.goto('/#/jobs/19/tasks');
      const row = page.locator('tr.material-row', { hasText: material.description }).first();
      await row.getByRole('button', { name: 'Order' }).click();
      const dialog = page.getByRole('dialog', { name: 'Order' });
      const vendor = dialog.getByRole('combobox', { name: /Vendor/ });
      await expect(vendor).toHaveValue(String(newest.business_id));
      await expect(vendor.locator('option').first()).toContainText(newest.business_name);
      await expect(dialog.getByLabel(/^Price/)).toHaveValue(Number(newest.last_price).toFixed(2));
      await expect(dialog.getByText(/Open drafts for this vendor/)).toHaveCount(0);   // seed has no drafts
    });

    await test.step('Create PO: lands on the PO with the line, Code and SKU columns', async () => {
      const dialog = page.getByRole('dialog', { name: 'Order' });
      await dialog.getByLabel(/Vendor SKU/).fill(`${stamp}-SKU`);
      await dialog.getByRole('button', { name: 'Create PO' }).click();
      await expect(page).toHaveURL(/#\/purchase-orders\/\d+$/);
      poUrl = page.url();
      poId = Number(poUrl.split('/').pop());
      poNumber = (await api.get(`/api/purchase-orders/${poId}/`)).po_number;
      await dismissOverlay(page);
      await expect(page.getByRole('heading', { name: /Purchase Order PO/ })).toBeVisible();
      await expect(page.locator('p', { has: page.getByText('Vendor:') })).toContainText(newest.business_name);
      await expect(page.getByRole('columnheader', { name: 'SKU' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Code' })).toBeVisible();
      await expect(page.getByRole('cell', { name: `${stamp}-SKU` })).toBeVisible();
      await expect(page.getByRole('cell', { name: 'BBPLY.5' })).toBeVisible();
    });

    await test.step('Append or new is explicit: a second order offers the draft, nothing preselected', async () => {
      // Large qty so the shelf can't cover it (a covered row reads On Hand and has no Order button).
      // Backdrop (never deleted: materials answer 405 on destroy; DB rebuilt each run): a second pending material on the same job and item (not the flow under test).
      const second = await api.post('/api/jobs/19/materials/', {
        description: `${stamp} second sheet`, quantity: '500', units: 'sheet', inventory_item: 30,
        unit_cost: '73.33', accounting_category: material.accounting_category,
      });
      await page.goto('/#/jobs/19/tasks');
      const row = page.locator('tr.material-row', { hasText: `${stamp} second sheet` });
      await row.getByRole('button', { name: 'Order' }).click();
      const dialog = page.getByRole('dialog', { name: 'Order' });
      const addTo = dialog.getByRole('radio', { name: new RegExp(`Add to ${poNumber}`) });
      await expect(addTo).toBeVisible();
      await expect(addTo).not.toBeChecked();
      await expect(dialog.getByRole('radio', { name: 'Start a new PO' })).not.toBeChecked();
      await expect(dialog.getByRole('button', { name: 'Create PO' })).toBeDisabled();
      await addTo.check();
      await dialog.getByRole('button', { name: `Add to ${poNumber}` }).click();
      await expect(page).toHaveURL(poUrl);
      await dismissOverlay(page);
      await expect(page.getByRole('cell', { name: `${stamp} second sheet` })).toBeVisible();
      const po = await api.get(`/api/purchase-orders/${poId}/`);
      expect(po.line_items).toHaveLength(2);
      expect((await api.get(`/api/materials/${second.material_id}/`)).po_line_item_id).not.toBeNull();
    });

    await test.step('Add Line Item → attach to an existing material creates no duplicate', async () => {
      const before = (await api.get('/api/jobs/19/')).materials.length;
      const third = await api.post('/api/jobs/19/materials/', {
        description: `${stamp} third sheet`, quantity: '500', units: 'sheet', inventory_item: 30,
        unit_cost: '73.33', accounting_category: material.accounting_category,
      });
      await page.goto(poUrl);
      await page.getByRole('button', { name: 'Add Line Item' }).click();
      await page.getByLabel('From Inventory').check();
      await page.getByPlaceholder('Search jobs…').fill('08008');
      await page.getByRole('button', { name: /08008/ }).first().click();
      const choice = page.getByRole('radio', { name: new RegExp(`${stamp} third sheet`) });
      await expect(choice).toBeVisible();
      await expect(choice).not.toBeChecked();
      await expect(page.getByRole('button', { name: 'Add', exact: true })).toBeDisabled();
      await choice.check();
      await expect(page.getByText(/BBPLY\.5 — /)).toBeVisible();     // item set and locked
      await page.getByLabel(/Qty/).fill('1');
      await page.getByRole('button', { name: 'Add', exact: true }).click();
      // The line takes the catalog item's description (the item is locked), not the material's,
      // so assert the new third row by count and the material's po_line_item_id below.
      await expect(page.getByRole('cell', { name: 'BBPLY.5' })).toHaveCount(3);
      const lines = (await api.get(`/api/purchase-orders/${poId}/`)).line_items;
      expect(lines).toHaveLength(3);
      expect((await api.get('/api/jobs/19/')).materials.length).toBe(before + 1);   // the one we made, no duplicate
      expect((await api.get(`/api/materials/${third.material_id}/`)).po_line_item_id).not.toBeNull();
    });

  } finally {
    // Always runs, so a mid-test failure can't leak the draft PO into the next run.
    // The backdrop materials are not deleted: MaterialViewSet.destroy answers 405 by
    // design, and the e2e DB is rebuilt every run.
    if (poId) {
      const po = await api.get(`/api/purchase-orders/${poId}/`);
      // Draft delete with linked materials needs a sever decision per linked line
      // (PurchaseOrderDetailPage.runDelete sends the same body).
      const decisions = Object.fromEntries(
        po.line_items.filter((l) => l.material).map((l) => [l.line_item_id, 'keep']));
      await api.delWith(`/api/purchase-orders/${poId}/?confirm=true`, { sever_decisions: decisions });
    }
    await api.dispose();
  }
});

test('§11 catalog order with no history opens in search mode', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const items = (await api.get('/api/inventory/?page_size=100&is_active=true')).results;
  let bare = null;
  for (const it of items) {
    const h = await api.get(`/api/inventory/${it.inventory_item_id}/vendor-history/`);
    if (!h.vendors.length && !it.code.startsWith('LOT-')) { bare = it; break; }
  }
  await api.dispose();
  test.skip(!bare, 'seed gap: every catalog item has vendor history');
  await page.goto('/#/catalog');
  const row = page.getByRole('row', { name: new RegExp(bare.code) }).first();
  await row.getByRole('button', { name: 'order' }).click();
  const dialog = page.getByRole('dialog', { name: 'Order' });
  await expect(dialog.getByPlaceholder('Search business…')).toBeVisible();
  await expect(dialog.getByRole('combobox', { name: /Vendor/ })).toHaveCount(0);
  await expect(dialog.getByText('back to recent vendors')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Create PO' })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('§11 email → Create new (PO) with a matched sender carries the contact', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  let emailId = null, poId = null, createdContactId = null, attachedContactId = null;
  try {
    const list = await api.get('/api/emails/?page_size=50');
    const emails = list.results || list;
    const unlinked = (e) => !e.purchase_order && !e.job;
    const email = emails.find((e) => unlinked(e) && /Invoice MNH-20441/.test(e.subject || ''))
      || emails.find(unlinked);
    test.skip(!email, 'seed gap: no unlinked email');
    emailId = email.email_record_id;
    // Backdrop: make the sender a known vendor contact so resolution matches
    // (the seed's vendor-invoice sender has no contact). Business 61 is a
    // seed vendor (Moore Newton Hardwoods).
    const info = await api.get(`/api/emails/${emailId}/sender-info/`);
    let contact = info.matching_contacts[0];
    if (!contact) {
      const created = await api.post('/api/contacts/', {
        first_name: 'Vendor', last_name: stamp, email: info.sender_email,
        phones: [{ number: '555-0199', label: 'work' }], business_id: 61,
      });
      createdContactId = created.contact_id;
      contact = { id: created.contact_id };
    }
    let fetched = await api.get(`/api/contacts/${contact.id}/`);
    if (!fetched.business) {
      // Order-independence: an earlier spec (email/create-job-modal) may have
      // created a business-less contact for this sender. Attach the seed
      // vendor for the duration of this test; restored in finally.
      await api.patch(`/api/contacts/${contact.id}/`, { business_id: 61 });
      if (!createdContactId) attachedContactId = contact.id;
      fetched = await api.get(`/api/contacts/${contact.id}/`);
    }
    const contactBusinessId = fetched.business?.business_id;
    expect(contactBusinessId).toBeTruthy();

    await page.goto(`/#/email/${emailId}`);
    const panel = page.getByRole('complementary');
    const poSection = panel.locator('section', { has: page.getByRole('heading', { name: 'Purchase Order' }) });
    await poSection.getByRole('button', { name: 'Create new' }).click();
    const dialog = page.getByRole('dialog', { name: 'Order' });
    await expect(dialog.getByRole('heading', { name: 'Sender' })).toBeVisible();
    await dialog.getByRole('button', { name: 'Create PO' }).click();
    await expect(page).toHaveURL(/#\/purchase-orders\/\d+$/);
    await dismissOverlay(page);
    poId = Number(page.url().split('/').pop());
    const po = await api.get(`/api/purchase-orders/${poId}/`);
    expect(po.contact).toBe(contact.id);
    expect(po.business).toBe(contactBusinessId);
    expect((await api.get(`/api/emails/${emailId}/`)).purchase_order).toBe(poId);
  } finally {
    // Always runs; each step is independent so one failure doesn't skip the rest.
    const attempt = async (fn) => { try { await fn(); } catch { /* already gone / never linked */ } };
    if (emailId) await attempt(() => api.post(`/api/emails/${emailId}/unlink-from-po/`, {}));
    if (poId) await attempt(() => api.del(`/api/purchase-orders/${poId}/?confirm=true`));
    // Only a contact THIS run created — never a seed match.
    if (createdContactId) await attempt(() => api.del(`/api/contacts/${createdContactId}/?confirm=true`));
    // A business this run attached to a pre-existing, business-less contact.
    if (attachedContactId) await attempt(() => api.patch(`/api/contacts/${attachedContactId}/`, { business_id: null }));
    await api.dispose();
  }
});

test('§11 guard: a worker sees no Order control and the API answers 403', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: personas.worker.storageState });
  const page = await ctx.newPage();
  await page.goto('/#/jobs/19/tasks');
  await expect(page.locator('tr.material-row').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Order' })).toHaveCount(0);
  const api = await apiAs(personas.worker);
  const r = await api.postRaw('/api/materials/6/order/', { po: { business: 59 } });
  expect(r.status()).toBe(403);
  await api.dispose();
  await ctx.close();
});
