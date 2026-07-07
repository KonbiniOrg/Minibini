// api.js dispatches `minibini:session-expired` when an authenticated-only
// call comes back unauthenticated (401, or DRF's 403 "credentials were not
// provided"), so App.svelte can bounce to the login screen instead of every
// component degrading silently. Permission-denied 403s must NOT trigger it.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '@/lib/api.js';

function mockFetchJson(status, body) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(body),
  });
}

describe('api session-expiry dispatch', () => {
  let expired;
  const listener = () => { expired = true; };

  beforeEach(() => {
    expired = false;
    window.addEventListener('minibini:session-expired', listener);
  });

  afterEach(() => {
    window.removeEventListener('minibini:session-expired', listener);
    vi.restoreAllMocks();
  });

  it('dispatches on a 403 with the unauthenticated detail', async () => {
    mockFetchJson(403, { detail: 'Authentication credentials were not provided.' });
    await expect(api.get('/api/settings/units/')).rejects.toThrow();
    expect(expired).toBe(true);
  });

  it('dispatches on a 401', async () => {
    mockFetchJson(401, { detail: 'Not authenticated.' });
    await expect(api.get('/api/jobs/')).rejects.toThrow();
    expect(expired).toBe(true);
  });

  it('does NOT dispatch on a permission-denied 403', async () => {
    mockFetchJson(403, { detail: 'You do not have permission to perform this action.' });
    await expect(api.post('/api/jobs/', {})).rejects.toThrow();
    expect(expired).toBe(false);
  });

  it('does NOT dispatch for auth endpoints (logged-out is normal there)', async () => {
    mockFetchJson(403, { detail: 'Authentication credentials were not provided.' });
    await expect(api.get('/api/auth/me/')).rejects.toThrow();
    expect(expired).toBe(false);
  });

  it('does NOT dispatch on success', async () => {
    mockFetchJson(200, { ok: true });
    await api.get('/api/jobs/');
    expect(expired).toBe(false);
  });
});
