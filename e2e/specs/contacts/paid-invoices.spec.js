// Paid invoices reach the contact/business detail pages. The invoice list
// endpoint defaults to the 'open' status preset, so the pages must ask for
// status=all or the "show N paid" toggle has nothing behind it (RM report,
// 2026-10-11: converted customers with only paid invoices showed "No open
// invoices"). Found by SHAPE: any paid invoice whose job's contact has a
// business.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

let target = null;

test.beforeAll(async () => {
  const api = await apiAs(personas.finjobs);
  try {
    const paid = await api.get('/api/invoices/?status=paid&summary=true&page_size=100');
    for (const inv of paid.results || []) {
      const job = await api.get(`/api/jobs/${inv.job}/`);
      if (!job.contact) continue;  // job detail carries the contact as a plain id
      const contact = await api.get(`/api/contacts/${job.contact}/`);
      if (contact.business) {
        target = {
          business: contact.business.business_id,
          contact: contact.contact_id,
          number: inv.display_number || inv.invoice_number,
        };
        break;
      }
    }
  } finally {
    await api.dispose();
  }
});

test.use({ storageState: personas.finjobs.storageState });

for (const kind of ['businesses', 'contacts']) {
  test(`${kind} page offers "show N paid" and reveals the paid invoice`, async ({ page }) => {
    test.skip(!target, 'seed gap: no paid invoice on a business-attached job');
    const id = kind === 'businesses' ? target.business : target.contact;
    await page.goto(`/#/${kind}/${id}`);
    const section = page.locator('[data-section="invoices"]');
    await expect(section).toBeVisible();
    // Before the bug fix the toggle was missing and the section was only the
    // empty text; the toggle in the head is what proves the paid rows arrived.
    const toggle = section.getByRole('button', { name: /show \d+ paid/ });
    await expect(toggle).toBeVisible();
    // Nothing open: the same dashed box as an empty section, with "open" wording.
    const box = section.locator('.empty-box');
    if (await box.count()) await expect(box).toHaveText('No open invoices.');
    await toggle.click();
    await expect(section).toContainText(target.number);
    await expect(box).toHaveCount(0);
  });
}
