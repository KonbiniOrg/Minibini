// Contact detail page (contacts UI redesign, 2026-10-10 —
// docs/plans/2026-10-10-contacts-ui-redesign.md): banner, the Contact and
// Business identity panels (mailto link, "Also here" siblings), Recent Jobs
// without a Contact column, and the Delete… modal on a deletable contact.
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

  test('banner, identity panels, Recent Jobs for a contact that has jobs', async ({ page }) => {
    test.skip(!business, 'seed gap: no business with ≥2 contacts and both open and closed jobs');
    const jobsByContact = new Map();
    for (const j of business.jobs) jobsByContact.set(j.contact, [...(jobsByContact.get(j.contact) || []), j]);
    const contactId = [...jobsByContact.keys()][0];
    const contact = business.contacts.find((c) => c.contact_id === contactId);
    const myJobs = jobsByContact.get(contactId);
    const closed = myJobs.filter((j) => CLOSED_JOB.has(j.status)).length;
    const siblings = business.contacts.filter((c) => c.contact_id !== contactId);

    await page.goto(`/#/contacts/${contactId}`);
    await expect(page.getByRole('heading', { name: contact.name })).toBeVisible();

    await test.step('Banner: business link, New Job button, Edit, Deactivate placeholder (the contact has jobs)', async () => {
      const banner = page.locator('.customer-header');
      await expect(banner.getByRole('link', { name: business.business_name })).toHaveAttribute('href', `#/businesses/${business.business_id}`);
      if (contactId === business.default_contact.contact_id) {
        await expect(banner.getByText('default contact')).toBeVisible();
      }
      await expect(page.getByRole('button', { name: 'New Job', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Edit' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Deactivate' })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Delete…' })).toHaveCount(0);
    });

    await test.step('Contact panel: email is a mailto link', async () => {
      await expect(page.getByRole('link', { name: contact.email })).toHaveAttribute('href', `mailto:${contact.email}`);
    });

    await test.step('Business panel: links the business and lists the other contacts under "Also here"', async () => {
      const panel = page.locator('.identity .panel', { hasText: 'Also here' });
      await expect(panel.getByRole('link', { name: business.business_name })).toBeVisible();
      for (const s of siblings) {
        await expect(panel.getByRole('link', { name: s.name })).toHaveAttribute('href', `#/contacts/${s.contact_id}`);
      }
    });

    await test.step('Recent Jobs: no Contact column; closed jobs sit behind "show N completed"', async () => {
      const jobs = page.locator('[data-section="jobs"]');
      await expect(jobs.getByRole('heading', { name: 'Recent Jobs' })).toBeVisible();
      await expect(jobs.locator('thead th', { hasText: 'Contact' })).toHaveCount(0);
      await expect(jobs.locator('tbody tr')).toHaveCount(myJobs.length - closed);
      if (closed > 0) {
        await jobs.getByRole('button', { name: `show ${closed} completed` }).click();
        await expect(jobs.locator('tbody tr')).toHaveCount(myJobs.length);
      }
    });

    await test.step('New Job in the banner opens the job modal with this contact preselected', async () => {
      await page.getByRole('button', { name: 'New Job', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'New job' });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText(contact.name)).toBeVisible();
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
    });
  });

  test('a job-less contact with a sibling offers Delete…; the modal deletes it and lands on the list', async ({ page }) => {
    test.skip(!business, 'seed gap: no business with ≥2 contacts and both open and closed jobs');
    const api = await apiAs(personas.finjobs);
    const stamp = `e2e-${Date.now().toString(36)}`;
    let created;
    try {
      created = await api.post('/api/contacts/', {
        first_name: stamp, last_name: 'Deletable', email: `${stamp}-c@example.invalid`,
        mobile_number: '555-0198', business_id: business.business_id,
      });
    } finally {
      await api.dispose();
    }

    await page.goto(`/#/contacts/${created.contact_id}`);
    await page.getByRole('button', { name: 'Delete…' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete contact' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete contact' }).click();
    await expect(page).toHaveURL(/#\/contacts$/);
    await expect(page.getByText(/deleted/i).first()).toBeVisible();
  });
});
