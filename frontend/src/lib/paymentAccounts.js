import { api } from './api.js';

// Module-level cache so pages don't re-fetch on every mount.
let _cache = null;
let _inflight = null;

/**
 * Return the configured payment accounts as parsed JSON. Cached.
 */
export async function getPaymentAccounts({ force = false } = {}) {
  if (!force && _cache !== null) return _cache;
  if (_inflight) return _inflight;

  _inflight = (async () => {
    try {
      const data = await api.get('/api/settings/');
      const raw = data?.qbo_payment_accounts || '[]';
      _cache = JSON.parse(raw);
      return _cache;
    } catch (err) {
      if (err.status === 404) {
        _cache = [];
        return _cache;
      }
      throw err;
    } finally {
      _inflight = null;
    }
  })();
  return _inflight;
}

/** Invalidate the cache. Call after saving the settings form. */
export function invalidatePaymentAccounts() {
  _cache = null;
}

/** Fetch the fresh list from QBO — for the settings Refresh button. */
export async function fetchFromQBO() {
  const data = await api.get('/api/qbo/payment-accounts/');
  return data?.payment_accounts || [];
}

/** Save the enabled-accounts JSON to Configuration. */
export async function savePaymentAccounts(accounts) {
  await api.patch('/api/settings/', {
    qbo_payment_accounts: JSON.stringify(accounts),
  });
  invalidatePaymentAccounts();
}
