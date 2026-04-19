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

export const api = {
  get: (url) => request('GET', url),
  post: (url, data) => request('POST', url, data),
  patch: (url, data) => request('PATCH', url, data),
  put: (url, data) => request('PUT', url, data),
  delete: (url, data = null) => request('DELETE', url, data),
};
