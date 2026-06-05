import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import {
  getPaymentAccounts,
  invalidatePaymentAccounts,
  fetchFromQBO,
  savePaymentAccounts,
} from '@/lib/paymentAccounts.js';

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  invalidatePaymentAccounts(); // clear module-level cache between tests
});

describe('getPaymentAccounts', () => {
  it('fetches and parses the configured JSON on a cache miss', async () => {
    api.get.mockResolvedValue({ qbo_payment_accounts: '[{"id":1}]' });
    const result = await getPaymentAccounts();
    expect(result).toEqual([{ id: 1 }]);
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('returns the cache without refetching on a second call', async () => {
    api.get.mockResolvedValue({ qbo_payment_accounts: '[]' });
    await getPaymentAccounts();
    await getPaymentAccounts();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('refetches when force is set', async () => {
    api.get.mockResolvedValue({ qbo_payment_accounts: '[]' });
    await getPaymentAccounts();
    await getPaymentAccounts({ force: true });
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it('dedupes concurrent in-flight requests', async () => {
    let resolveGet;
    api.get.mockReturnValue(new Promise((r) => { resolveGet = r; }));
    const p1 = getPaymentAccounts();
    const p2 = getPaymentAccounts();
    resolveGet({ qbo_payment_accounts: '[]' });
    await Promise.all([p1, p2]);
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('treats a 404 as an empty list', async () => {
    api.get.mockRejectedValue({ status: 404 });
    expect(await getPaymentAccounts()).toEqual([]);
  });

  it('rethrows non-404 errors', async () => {
    api.get.mockRejectedValue({ status: 500 });
    await expect(getPaymentAccounts()).rejects.toEqual({ status: 500 });
  });

  it('defaults to an empty list when the field is absent', async () => {
    api.get.mockResolvedValue({});
    expect(await getPaymentAccounts()).toEqual([]);
  });
});

describe('fetchFromQBO', () => {
  it('returns the payment_accounts array from QBO', async () => {
    api.get.mockResolvedValue({ payment_accounts: [{ x: 1 }] });
    expect(await fetchFromQBO()).toEqual([{ x: 1 }]);
  });
});

describe('savePaymentAccounts', () => {
  it('patches the serialized accounts and invalidates the cache', async () => {
    api.patch.mockResolvedValue({});
    api.get.mockResolvedValue({ qbo_payment_accounts: '[{"id":9}]' });

    await savePaymentAccounts([{ id: 1 }]);
    expect(api.patch).toHaveBeenCalledWith('/api/settings/', {
      qbo_payment_accounts: '[{"id":1}]',
    });

    // cache was invalidated, so the next read hits the api again
    await getPaymentAccounts();
    expect(api.get).toHaveBeenCalledTimes(1);
  });
});
