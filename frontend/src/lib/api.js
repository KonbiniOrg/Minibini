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
    throw new Error(`Server error (${response.status})`);
  }

  const json = await response.json();

  if (!response.ok) {
    const error = new Error(json.detail || json.error || 'Request failed');
    error.status = response.status;
    error.data = json;
    throw error;
  }

  return json;
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
    throw new Error(`Server error (${response.status})`);
  }
  const json = await response.json();
  if (!response.ok) {
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
