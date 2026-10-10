// "Create new" (Job) on the email action panel opens EmailCreateJobModal
// over the email (2026-10-10, replacing /email/:id/create-job). A create
// lands on the new job; the email is unlinked again afterwards so reruns
// start from the seed state.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

test('email → Create new (Job) modal → create lands on the job', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const list = await api.get('/api/emails/?page_size=50');
  const email = (list.results || list).find((e) => !e.job);
  test.skip(!email, 'seed gap: no email without a linked job');

  await page.goto(`/#/email/${email.email_record_id}`);
  const panel = page.getByRole('complementary');
  const jobSection = panel.locator('section', { has: page.getByRole('heading', { name: 'Job', exact: true }) });
  await jobSection.getByRole('button', { name: 'Create new' }).click();

  const dialog = page.getByRole('dialog', { name: 'Create job from email' });
  await expect(dialog.getByRole('heading', { name: 'Sender' })).toBeVisible();
  const name = `${stamp} from email`;
  await dialog.getByLabel('Job Name *').fill(name);
  // When the sender resolves to a NEW contact, the seed's one-word sender
  // names leave Last Name empty (required) and a phone is required
  // server-side — fill both so the contact can be created.
  const lastName = dialog.getByLabel('Last Name *');
  if (await lastName.count() && !(await lastName.inputValue())) await lastName.fill(stamp);
  const mobile = dialog.getByLabel('Mobile');
  if (await mobile.count()) await mobile.fill('555-0103');
  await dialog.getByRole('button', { name: 'Create Job' }).click();

  await expect(page).toHaveURL(/#\/jobs\/\d+$/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: new RegExp(`${name}$`) })).toBeVisible();

  await api.post(`/api/emails/${email.email_record_id}/unlink-from-job/`, {});
  await api.dispose();
});
