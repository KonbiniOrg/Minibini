function getCsrfToken() {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
}

async function request(method, url, data = null) {
  const options = {
    method,
    headers: {},
    credentials: 'same-origin',
  };

  if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)) {
    options.headers['Content-Type'] = 'application/json';
    options.headers['X-CSRFToken'] = getCsrfToken();
  }

  if (data !== null) {
    options.body = JSON.stringify(data);
  }

  const response = await fetch(url, options);

  const contentType = response.headers.get('content-type') || '';

  if (!contentType.includes('application/json')) {
    // A non-JSON body (nginx error page, crashed request) still gets a
    // status so callers can branch on it; .data stays null.
    const error = new Error(`Server error (${response.status})`);
    error.status = response.status;
    error.data = null;
    throw error;
  }

  const json = await response.json();

  if (!response.ok) {
    notifyIfSessionExpired(url, response.status, json);
    const error = new Error(json.detail || json.error || 'Request failed');
    error.status = response.status;
    error.data = json;
    throw error;
  }

  return json;
}

// DRF (SessionAuthentication) answers an *unauthenticated* request with this
// exact detail (status 403; 401 from other authenticators). A 403 for a
// logged-in user lacking permission says "You do not have permission…" and
// must NOT be treated as expiry.
const UNAUTHENTICATED_DETAIL = 'Authentication credentials were not provided.';

function notifyIfSessionExpired(url, status, json) {
  // The auth-check endpoint legitimately 401/403s while logged out.
  if (url.startsWith('/api/auth/')) return;
  const expired = status === 401
    || (status === 403 && json?.detail === UNAUTHENTICATED_DETAIL);
  if (expired && typeof window !== 'undefined') {
    // App.svelte listens and bounces to the login screen — without this,
    // every fetch-and-fallback component just degrades silently.
    window.dispatchEvent(new CustomEvent('minibini:session-expired'));
  }
}

async function postMultipart(url, formData) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() },
    credentials: 'same-origin',
    body: formData,
  });
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    const error = new Error(`Server error (${response.status})`);
    error.status = response.status;
    error.data = null;
    throw error;
  }
  const json = await response.json();
  if (!response.ok) {
    notifyIfSessionExpired(url, response.status, json);
    const error = new Error(json.detail || json.error || 'Request failed');
    error.status = response.status;
    error.data = json;
    throw error;
  }
  return json;
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, data) => request('POST', url, data),
  patch: (url, data) => request('PATCH', url, data),
  put: (url, data) => request('PUT', url, data),
  delete: (url, data = null) => request('DELETE', url, data),
  postMultipart,
};

/**
 * Extract a human-readable message from a thrown api error, digging into the
 * DRF response envelopes: `{detail}`, `{error}`, or field errors
 * `{field: ['msg']}` (returns the first field's first message). Falls back to
 * the Error's message, then `fallback`. Use this instead of `e.data.detail`
 * (which misses field-validation errors) or raw `JSON.stringify(e.data)`.
 */
export function errorMessage(err, fallback = 'Something went wrong.') {
  const data = err?.data;
  if (data && typeof data === 'object') {
    if (typeof data.detail === 'string') return data.detail;
    if (typeof data.error === 'string') return data.error;
    for (const value of Object.values(data)) {
      if (Array.isArray(value) && value.length && typeof value[0] === 'string') return value[0];
      if (typeof value === 'string') return value;
    }
  }
  return err?.message || fallback;
}
