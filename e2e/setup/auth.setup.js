// Playwright "setup" project (runs before the specs): logs each persona in
// once through the real login form and saves the session to
// e2e/.auth/<persona>.json (docs/designs/e2e-testing.md §2). Specs never see the login
// form — they start already authenticated via storageState.
import fs from 'node:fs';
import path from 'node:path';
import { expect, test as setup } from '@playwright/test';
import { E2E_PASSWORD, personas } from '../fixtures/personas.js';

for (const [name, persona] of Object.entries(personas)) {
  setup(`authenticate ${name} (${persona.username})`, async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('Username').fill(persona.username);
    await page.getByLabel('Password').fill(E2E_PASSWORD);
    await page.getByRole('button', { name: 'Log In' }).click();
    // The app header (shift strip) only renders once authenticated.
    await expect(page.getByRole('banner')).toBeVisible();
    fs.mkdirSync(path.dirname(persona.storageState), { recursive: true });
    await page.context().storageState({ path: persona.storageState });
  });
}
