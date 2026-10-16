// Business detail page (contacts UI redesign, 2026-10-10 —
// docs/plans/2026-10-10-contacts-ui-redesign.md): banner actions, the
// always-visible Contacts table with Set as default / New job per row, and
// Recent Jobs' "show N completed" toggle.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';
import { findCustomerBusiness, CLOSED_JOB } from './_customer.js';

let business = null;

test.beforeAll(async () => {
  business = await findCustomerBusiness();
});

test.describe('with can_manage_jobs', () => {
  test.use({ storageState: personas.finjobs.storageState });

  test('banner actions, Contacts table, Recent Jobs toggle, Set as default', async ({ page }) => {
    test.skip(!business, 'seed gap: no business with ≥2 contacts and both open and closed jobs');
    const originalDefault = business.default_contact.contact_id;
    const other = business.contacts.find((c) => c.contact_id !== originalDefault);
    const closed = business.jobs.filter((j) => CLOSED_JOB.has(j.status)).length;
    const open = business.jobs.length - closed;

    await page.goto(`/#/businesses/${business.business_id}`);
    await expect(page.getByRole('heading', { name: business.business_name })).toBeVisible();

    await test.step('Banner: New Job button, Edit, and Deactivate (the business has jobs, so no Delete)', async () => {
      await expect(page.getByRole('button', { name: 'New Job', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Edit' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Deactivate' })).toBeEnabled();
      await expect(page.getByRole('button', { name: 'Delete…' })).toHaveCount(0);
    });

    const contacts = page.locator('[data-section="contacts"]');
    await test.step('Contacts table lists every contact, with the default chip on the default contact', async () => {
      await expect(contacts.locator('tbody tr')).toHaveCount(business.contacts.length);
      const defaultRow = contacts.locator('tbody tr', { hasText: business.default_contact.name });
      await expect(defaultRow.getByText('default', { exact: true })).toBeVisible();
      await expect(defaultRow.getByRole('button', { name: 'Set as default' })).toBeDisabled();
    });

    const jobs = page.locator('[data-section="jobs"]');
    await test.step('Recent Jobs hides closed jobs; "show N completed" extends the table; "hide" collapses it', async () => {
      await expect(jobs.getByRole('heading', { name: 'Recent Jobs' })).toBeVisible();
      await expect(jobs.locator('tbody tr')).toHaveCount(open);
      await jobs.getByRole('button', { name: `show ${closed} completed` }).click();
      await expect(jobs.locator('tbody tr')).toHaveCount(business.jobs.length);
      await jobs.getByRole('button', { name: `hide ${closed} completed` }).click();
      await expect(jobs.locator('tbody tr')).toHaveCount(open);
    });

    await test.step('New job from a Contacts row opens the job modal with that contact preselected', async () => {
      const row = contacts.locator('tbody tr', { hasText: other.name });
      await row.getByRole('button', { name: 'New job' }).click();
      const dialog = page.getByRole('dialog', { name: 'New job' });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText(other.name)).toBeVisible();
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
    });

    await test.step('Set as default moves the chip (no confirm — it is reversible); then put it back', async () => {
      await contacts.locator('tbody tr', { hasText: other.name }).getByRole('button', { name: 'Set as default' }).click();
      const newDefaultRow = contacts.locator('tbody tr', { hasText: other.name });
      await expect(newDefaultRow.getByText('default', { exact: true })).toBeVisible();
      const originalRow = contacts.locator('tbody tr', { hasText: business.default_contact.name });
      await originalRow.getByRole('button', { name: 'Set as default' }).click();
      await expect(originalRow.getByText('default', { exact: true })).toBeVisible();
    });
  });

  test('a fresh business with one contact and no jobs offers Delete… and the modal deletes it', async ({ page }) => {
    const api = await apiAs(personas.finjobs);
    const stamp = `e2e-${Date.now().toString(36)}`;
    let created;
    try {
      const contact = await api.post('/api/contacts/', {
        first_name: stamp, last_name: 'Deletable', email: `${stamp}-del@example.invalid`, mobile_number: '555-0199',
      });
      created = await api.post('/api/businesses/', {
        business_name: `${stamp} Deletable Co`, default_contact_id: contact.contact_id,
      });
      await api.patch(`/api/contacts/${contact.contact_id}/`, { business_id: created.business_id });
    } finally {
      await api.dispose();
    }

    await page.goto(`/#/businesses/${created.business_id}`);
    await test.step('Empty sections keep their heading and say "yet"', async () => {
      const jobs = page.locator('[data-section="jobs"]');
      await expect(jobs.getByRole('heading', { name: 'Recent Jobs' })).toBeVisible();
      await expect(jobs.locator('.empty-box')).toHaveText('No jobs yet.');
      await expect(page.locator('[data-section="invoices"] .empty-box')).toHaveText('No invoices yet.');
      await expect(page.locator('[data-section="pos"] .empty-box')).toHaveText('No purchase orders yet.');
    });
    await page.getByRole('button', { name: 'Delete…' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete business' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete business' }).click();
    await expect(page).toHaveURL(/#\/contacts$/);
    await expect(page.getByText(/deleted/i).first()).toBeVisible();
  });
});

test.describe('without can_manage_jobs', () => {
  test.use({ storageState: personas.worker.storageState });

  test('Guard: no banner actions and no row actions for a worker', async ({ page }) => {
    test.skip(!business, 'seed gap: no business with ≥2 contacts and both open and closed jobs');
    await page.goto(`/#/businesses/${business.business_id}`);
    await expect(page.getByRole('heading', { name: business.business_name })).toBeVisible();
    await expect(page.getByRole('button', { name: 'New Job', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Edit' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Deactivate' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Set as default' })).toHaveCount(0);
    await expect(page.locator('[data-section="contacts"] tbody tr')).toHaveCount(business.contacts.length);
  });
});
