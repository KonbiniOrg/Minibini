// Persona-authenticated APIRequestContexts for specs (docs/designs/
// e2e-testing.md §2). Used to read backdrop data and, sparingly, to create
// objects — only when the flow under test is the creation of that object.
import { request } from '@playwright/test';

const BASE_URL = 'http://localhost:9100';

// An APIRequestContext authenticated as a persona, with Django's CSRF
// convention wired up (csrftoken cookie → X-CSRFToken header on writes).
// Call .dispose() when done.
export async function apiAs(persona, baseURL = BASE_URL) {
  const ctx = await request.newContext({
    baseURL,
    storageState: persona.storageState,
  });
  const { cookies } = await ctx.storageState();
  const csrf = cookies.find((c) => c.name === 'csrftoken')?.value;
  return {
    get: async (url) => asJson(await ctx.get(url)),
    post: async (url, data) =>
      asJson(await ctx.post(url, { data, headers: { 'X-CSRFToken': csrf } })),
    dispose: () => ctx.dispose(),
  };
}

async function asJson(response) {
  if (!response.ok()) {
    throw new Error(
      `${response.url()} → ${response.status()}: ${await response.text()}`);
  }
  return response.json();
}
