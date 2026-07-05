// The thrown-error contract of api.js (see architecture-and-conventions.md
// → Error responses): every rejection carries .status and .data — including
// non-JSON bodies (nginx error pages), where .data is null — and
// errorMessage() is the one sanctioned reader for user-facing text.
import { describe, it, expect, vi } from 'vitest';
import { api, errorMessage } from '@/lib/api.js';

function mockFetch({ status, contentType = 'application/json', body = {} }) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => contentType },
    json: () => Promise.resolve(body),
  });
}

describe('api error shape', () => {
  it('attaches status and data on JSON errors', async () => {
    mockFetch({ status: 409, body: { detail: 'Scheme is referenced.' } });
    const err = await api.get('/api/x/').catch((e) => e);
    expect(err.status).toBe(409);
    expect(err.data).toEqual({ detail: 'Scheme is referenced.' });
    expect(err.message).toBe('Scheme is referenced.');
  });

  it('attaches status (data null) on non-JSON errors so callers can branch', async () => {
    mockFetch({ status: 502, contentType: 'text/html' });
    const err = await api.get('/api/x/').catch((e) => e);
    expect(err.status).toBe(502);
    expect(err.data).toBeNull();
    expect(err.message).toBe('Server error (502)');
  });

  it('field-keyed errors give a generic message but errorMessage() digs it out', async () => {
    mockFetch({ status: 400, body: { name: ['This field is required.'] } });
    const err = await api.post('/api/x/', {}).catch((e) => e);
    expect(err.message).toBe('Request failed');
    expect(errorMessage(err)).toBe('This field is required.');
  });

  it('errorMessage prefers detail, falls back through fields to the fallback', () => {
    expect(errorMessage({ data: { detail: 'Nope.' } })).toBe('Nope.');
    expect(errorMessage({ data: null, message: 'Server error (502)' }))
      .toBe('Server error (502)');
    expect(errorMessage({}, 'fallback text')).toBe('fallback text');
  });
});
