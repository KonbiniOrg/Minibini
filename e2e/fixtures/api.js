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
    patch: async (url, data) =>
      asJson(await ctx.patch(url, { data, headers: { 'X-CSRFToken': csrf } })),
    del: async (url) =>
      asJson(await ctx.delete(url, { headers: { 'X-CSRFToken': csrf } })),
    // Raw variants for guard steps that assert on the status code.
    postRaw: (url, data) =>
      ctx.post(url, { data, headers: { 'X-CSRFToken': csrf } }),
    patchRaw: (url, data) =>
      ctx.patch(url, { data, headers: { 'X-CSRFToken': csrf } }),
    dispose: () => ctx.dispose(),
  };
}

// Close the persona's open timeslip, if any — afterEach hygiene so a failed
// test can't leak a running session into the next one. API-based on purpose:
// error overlays can block UI clicks, and cleanup must never depend on the
// page being in a good state.
export async function closeOpenSession(persona) {
  const api = await apiAs(persona);
  try {
    const current = await api.get('/api/bleps/current/');
    const taskId = current?.task?.task_id ?? current?.task?.id ?? current?.task_id;
    if (taskId) {
      await api.post(`/api/tasks/${taskId}/stop-work/`, { prior_qty_handled: true });
    }
  } catch {
    // no open session (or already closed) — nothing to do
  } finally {
    await api.dispose();
  }
}

async function asJson(response) {
  if (!response.ok()) {
    throw new Error(
      `${response.url()} → ${response.status()}: ${await response.text()}`);
  }
  return response.json();
}
