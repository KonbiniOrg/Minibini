# Svelte SPA Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Svelte 5 SPA frontend for the Contacts section, with shared/full project structure supporting future frontend variants.

**Architecture:** Svelte 5 + Vite standalone app (no SvelteKit). Multi-app monorepo: `frontend/shared/` holds reusable components and API client, `frontend/full/` is the first app variant with its own routing, layout, and CSS. Vite proxies `/api/*` to Django in development; nginx serves the SPA in production.

**Tech Stack:** Svelte 5, Vite, svelte-spa-router, Django REST Framework (existing API)

**Design doc:** `docs/plans/2026-03-08-svelte-spa-design.md`

---

### Task 1: Scaffold frontend/full Vite + Svelte project

**Files:**
- Create: `frontend/full/package.json`
- Create: `frontend/full/vite.config.js`
- Create: `frontend/full/index.html`
- Create: `frontend/full/src/main.js`
- Create: `frontend/full/src/App.svelte`
- Create: `frontend/full/src/css/app.css`

**Step 1: Create directory structure**

```bash
mkdir -p frontend/full/src/css frontend/full/src/routes frontend/full/src/components frontend/shared/lib frontend/shared/components/contacts frontend/shared/stores
```

**Step 2: Initialize npm project and install dependencies**

```bash
cd frontend/full
npm init -y
npm install svelte svelte-spa-router
npm install -D vite @sveltejs/vite-plugin-svelte
```

**Step 3: Create vite.config.js**

```js
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'path';

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    alias: {
      '$shared': path.resolve(__dirname, '../shared'),
    },
  },
  server: {
    port: 9000,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
```

**Step 4: Create index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Minibini</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

**Step 5: Create src/main.js**

```js
import App from './App.svelte';
import { mount } from 'svelte';
import './css/app.css';

const app = mount(App, {
  target: document.getElementById('app'),
});

export default app;
```

**Step 6: Create src/App.svelte (minimal placeholder)**

```svelte
<script>
</script>

<h1>Minibini</h1>
<p>SPA is working.</p>
```

**Step 7: Create src/css/app.css (empty placeholder)**

```css
/* Global styles */
```

**Step 8: Verify it runs**

```bash
cd frontend/full
npx vite
```

Open `http://localhost:9000` — should show "Minibini" heading and "SPA is working."

**Step 9: Add .gitignore for node artifacts**

Create `frontend/.gitignore`:
```
node_modules/
dist/
```

**Step 10: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold Svelte 5 + Vite project structure"
```

---

### Task 2: API client (shared/lib/api.js)

**Files:**
- Create: `frontend/shared/lib/api.js`

**Step 1: Create the API wrapper**

```js
function getCsrfToken() {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
}

async function request(method, url, data = null) {
  const options = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
    },
    credentials: 'same-origin',
  };

  if (data !== null) {
    options.body = JSON.stringify(data);
  }

  const response = await fetch(url, options);

  if (response.status === 204) {
    return null;
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
  delete: (url) => request('DELETE', url),
};
```

**Step 2: Verify import works from full app**

Update `frontend/full/src/App.svelte` temporarily:

```svelte
<script>
  import { api } from '$shared/lib/api.js';
  console.log('api client loaded:', api);
</script>

<h1>Minibini</h1>
<p>SPA is working.</p>
```

Run Vite, open browser console — should see "api client loaded:" with the object.

**Step 3: Commit**

```bash
git add frontend/shared/lib/api.js frontend/full/src/App.svelte
git commit -m "feat: add shared API client with CSRF handling"
```

---

### Task 3: Router and Nav setup

**Files:**
- Create: `frontend/full/src/components/Nav.svelte`
- Create: `frontend/full/src/routes/Home.svelte`
- Modify: `frontend/full/src/App.svelte`

**Step 1: Create Nav component**

```svelte
<script>
  import { link } from 'svelte-spa-router';
</script>

<nav>
  <a href="/" use:link>Home</a>
  | <a href="/contacts" use:link>Contacts</a>
  | <a href="/businesses" use:link>Businesses</a>
</nav>
<hr>
```

**Step 2: Create Home route**

```svelte
<h2>Home</h2>
<p>Welcome to Minibini.</p>
```

**Step 3: Update App.svelte with router**

```svelte
<script>
  import Router from 'svelte-spa-router';
  import Nav from './components/Nav.svelte';
  import Home from './routes/Home.svelte';

  const routes = {
    '/': Home,
  };
</script>

<h1>Minibini</h1>
<Nav />
<Router {routes} />
```

**Step 4: Verify routing works**

Run Vite, open `http://localhost:9000`. Should see nav links and Home content. Click links — URL should change (hash-based: `/#/contacts` etc.), though contacts will show "not found" since we haven't built those routes yet.

**Step 5: Commit**

```bash
git add frontend/full/src/
git commit -m "feat: add router, navigation, and home route"
```

---

### Task 4: Contact List

**Files:**
- Create: `frontend/shared/components/contacts/ContactList.svelte`
- Create: `frontend/full/src/routes/contacts/ContactListPage.svelte`
- Modify: `frontend/full/src/App.svelte` (add route)

**API endpoint:** `GET /api/contacts/` → `{ count, next, previous, results: [{ contact_id, first_name, middle_initial, last_name, name, email, mobile_number, work_number, home_number, addr1, addr2, addr3, city, municipality, postal_code, country_code, business }] }`

**Step 1: Create shared ContactList component**

This component receives contacts data as a prop and renders it. It does NOT fetch data itself.

```svelte
<script>
  const { contacts = [], onSelect = null } = $props();
</script>

{#if contacts.length === 0}
  <p>No contacts found.</p>
{:else}
  <table border="1">
    <thead>
      <tr>
        <th>Name</th>
        <th>Email</th>
        <th>Phone</th>
      </tr>
    </thead>
    <tbody>
      {#each contacts as contact}
        <tr>
          <td>
            {#if onSelect}
              <a href="#" onclick={(e) => { e.preventDefault(); onSelect(contact); }}>
                {contact.name}
              </a>
            {:else}
              {contact.name}
            {/if}
          </td>
          <td>{contact.email}</td>
          <td>{contact.work_number || contact.mobile_number || contact.home_number || ''}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
```

**Step 2: Create route page component**

The page component handles data fetching and passes data to the shared component.

```svelte
<script>
  import { api } from '$shared/lib/api.js';
  import ContactList from '$shared/components/contacts/ContactList.svelte';
  import { push } from 'svelte-spa-router';

  let contacts = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);

  async function loadContacts() {
    loading = true;
    error = null;
    try {
      const data = await api.get(`/api/contacts/?page=${page}`);
      contacts = data.results;
      count = data.count;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function handleSelect(contact) {
    push(`/contacts/${contact.contact_id}`);
  }

  $effect(() => {
    loadContacts();
  });
</script>

<h2>Contacts ({count})</h2>

<p><a href="#/contacts/new">New Contact</a></p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else}
  <ContactList {contacts} onSelect={handleSelect} />

  {#if count > 25}
    <p>
      {#if page > 1}
        <button onclick={() => { page--; }}>Previous</button>
      {/if}
      Page {page}
      {#if page * 25 < count}
        <button onclick={() => { page++; }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}
```

**Step 3: Add route to App.svelte**

Add to imports and routes map:

```js
import ContactListPage from './routes/contacts/ContactListPage.svelte';

const routes = {
  '/': Home,
  '/contacts': ContactListPage,
};
```

**Step 4: Verify**

Run Vite + Django. Navigate to `/#/contacts`. Should show paginated list of contacts from API. (Requires Django running on :8000 with test data loaded.)

**Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add contact list page with pagination"
```

---

### Task 5: Contact Detail

**Files:**
- Create: `frontend/shared/components/contacts/ContactDetail.svelte`
- Create: `frontend/full/src/routes/contacts/ContactDetailPage.svelte`
- Modify: `frontend/full/src/App.svelte` (add route)

**API endpoint:** `GET /api/contacts/{id}/` → single contact object

**Delete flow:** `DELETE /api/contacts/{id}/` → `{ confirm_required: true, impact: { jobs: N } }`, then `DELETE /api/contacts/{id}/?confirm=true` → 204

**Step 1: Create shared ContactDetail component**

```svelte
<script>
  const { contact, onEdit = null, onDelete = null } = $props();
</script>

<dl>
  <dt>Name</dt>
  <dd>{contact.name}</dd>

  <dt>Email</dt>
  <dd>{contact.email}</dd>

  {#if contact.work_number}
    <dt>Work</dt>
    <dd>{contact.work_number}</dd>
  {/if}

  {#if contact.mobile_number}
    <dt>Mobile</dt>
    <dd>{contact.mobile_number}</dd>
  {/if}

  {#if contact.home_number}
    <dt>Home</dt>
    <dd>{contact.home_number}</dd>
  {/if}

  {#if contact.addr1}
    <dt>Address</dt>
    <dd>
      {contact.addr1}
      {#if contact.addr2}<br>{contact.addr2}{/if}
      {#if contact.addr3}<br>{contact.addr3}{/if}
      {#if contact.city}<br>{contact.city}{/if}
      {#if contact.municipality}, {contact.municipality}{/if}
      {#if contact.postal_code} {contact.postal_code}{/if}
      {#if contact.country_code}<br>{contact.country_code}{/if}
    </dd>
  {/if}

  <dt>Business</dt>
  <dd>{contact.business || 'None'}</dd>
</dl>

<p>
  {#if onEdit}
    <button onclick={onEdit}>Edit</button>
  {/if}
  {#if onDelete}
    <button onclick={onDelete}>Delete</button>
  {/if}
</p>
```

**Step 2: Create route page component**

```svelte
<script>
  import { api } from '$shared/lib/api.js';
  import ContactDetail from '$shared/components/contacts/ContactDetail.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let contact = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let deleteConfirm = $state(null);

  async function loadContact() {
    loading = true;
    error = null;
    try {
      contact = await api.get(`/api/contacts/${params.id}/`);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleDelete() {
    if (!deleteConfirm) {
      try {
        const result = await api.delete(`/api/contacts/${params.id}/`);
        if (result && result.confirm_required) {
          deleteConfirm = result.impact;
        }
      } catch (e) {
        error = e.message;
      }
      return;
    }

    try {
      await api.delete(`/api/contacts/${params.id}/?confirm=true`);
      push('/contacts');
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    loadContact();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if contact}
  <h2>{contact.name}</h2>
  <ContactDetail
    {contact}
    onEdit={() => push(`/contacts/${params.id}/edit`)}
    onDelete={handleDelete}
  />

  {#if deleteConfirm}
    <p>
      <strong>Are you sure?</strong>
      This contact is associated with {deleteConfirm.jobs} job(s).
      <button onclick={handleDelete}>Yes, delete</button>
      <button onclick={() => { deleteConfirm = null; }}>Cancel</button>
    </p>
  {/if}

  <p><a href="#/contacts">Back to list</a></p>
{/if}
```

**Step 3: Add route to App.svelte**

```js
import ContactDetailPage from './routes/contacts/ContactDetailPage.svelte';

// Add to routes:
'/contacts/:id': ContactDetailPage,
```

**Step 4: Verify**

Navigate to `/#/contacts`, click a contact name → should show detail view. Delete button should trigger two-step confirmation.

**Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add contact detail page with delete confirmation"
```

---

### Task 6: Contact Form (create + edit)

**Files:**
- Create: `frontend/shared/components/contacts/ContactForm.svelte`
- Create: `frontend/full/src/routes/contacts/ContactFormPage.svelte`
- Modify: `frontend/full/src/App.svelte` (add routes)

**API endpoints:**
- Create: `POST /api/contacts/` with `{ first_name, last_name, email, ... }`
- Edit: `GET /api/contacts/{id}/` then `PATCH /api/contacts/{id}/` with changed fields
- Businesses for dropdown: `GET /api/businesses/` (paginated — may need all; for now use first page)

**Step 1: Create shared ContactForm component**

```svelte
<script>
  const {
    contact = null,
    businesses = [],
    onSubmit,
    onCancel,
    errors = null,
  } = $props();

  let form = $state({
    first_name: contact?.first_name || '',
    middle_initial: contact?.middle_initial || '',
    last_name: contact?.last_name || '',
    email: contact?.email || '',
    mobile_number: contact?.mobile_number || '',
    work_number: contact?.work_number || '',
    home_number: contact?.home_number || '',
    addr1: contact?.addr1 || '',
    addr2: contact?.addr2 || '',
    addr3: contact?.addr3 || '',
    city: contact?.city || '',
    municipality: contact?.municipality || '',
    postal_code: contact?.postal_code || '',
    country_code: contact?.country_code || '',
    business: contact?.business || '',
  });

  function handleSubmit(e) {
    e.preventDefault();
    const data = { ...form };
    if (data.business === '') {
      data.business = null;
    }
    onSubmit(data);
  }
</script>

<form onsubmit={handleSubmit}>
  {#if errors}
    <p><strong>Error:</strong> {errors}</p>
  {/if}

  <p>
    <label for="first_name"><strong>First Name *</strong></label><br>
    <input type="text" id="first_name" bind:value={form.first_name} required>
  </p>
  <p>
    <label for="middle_initial"><strong>Middle Initial</strong></label><br>
    <input type="text" id="middle_initial" bind:value={form.middle_initial}>
  </p>
  <p>
    <label for="last_name"><strong>Last Name *</strong></label><br>
    <input type="text" id="last_name" bind:value={form.last_name} required>
  </p>
  <p>
    <label for="email"><strong>Email *</strong></label><br>
    <input type="email" id="email" bind:value={form.email} required>
  </p>

  <fieldset>
    <legend><strong>Phone Numbers (at least one required)</strong></legend>
    <p>
      <label for="work_number"><strong>Work</strong></label><br>
      <input type="text" id="work_number" bind:value={form.work_number}>
    </p>
    <p>
      <label for="mobile_number"><strong>Mobile</strong></label><br>
      <input type="text" id="mobile_number" bind:value={form.mobile_number}>
    </p>
    <p>
      <label for="home_number"><strong>Home</strong></label><br>
      <input type="text" id="home_number" bind:value={form.home_number}>
    </p>
  </fieldset>

  <fieldset>
    <legend><strong>Address</strong></legend>
    <p>
      <label for="addr1"><strong>Address 1</strong></label><br>
      <input type="text" id="addr1" bind:value={form.addr1}>
    </p>
    <p>
      <label for="addr2"><strong>Address 2</strong></label><br>
      <input type="text" id="addr2" bind:value={form.addr2}>
    </p>
    <p>
      <label for="addr3"><strong>Address 3</strong></label><br>
      <input type="text" id="addr3" bind:value={form.addr3}>
    </p>
    <p>
      <label for="city"><strong>City</strong></label><br>
      <input type="text" id="city" bind:value={form.city}>
    </p>
    <p>
      <label for="municipality"><strong>Municipality</strong></label><br>
      <input type="text" id="municipality" bind:value={form.municipality}>
    </p>
    <p>
      <label for="postal_code"><strong>Postal Code</strong></label><br>
      <input type="text" id="postal_code" bind:value={form.postal_code}>
    </p>
    <p>
      <label for="country_code"><strong>Country Code</strong></label><br>
      <input type="text" id="country_code" bind:value={form.country_code} maxlength="3">
    </p>
  </fieldset>

  <p>
    <label for="business"><strong>Business</strong></label><br>
    <select id="business" bind:value={form.business}>
      <option value="">-- None --</option>
      {#each businesses as biz}
        <option value={biz.business_id}>{biz.business_name}</option>
      {/each}
    </select>
  </p>

  <p>
    <button type="submit">{contact ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>
```

**Step 2: Create route page component**

```svelte
<script>
  import { api } from '$shared/lib/api.js';
  import ContactForm from '$shared/components/contacts/ContactForm.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let contact = $state(null);
  let businesses = $state([]);
  let loading = $state(true);
  let errors = $state(null);

  async function load() {
    loading = true;
    try {
      const bizData = await api.get('/api/businesses/?page_size=100');
      businesses = bizData.results;

      if (isEdit) {
        contact = await api.get(`/api/contacts/${params.id}/`);
      }
    } catch (e) {
      errors = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(data) {
    errors = null;
    try {
      if (isEdit) {
        await api.patch(`/api/contacts/${params.id}/`, data);
        push(`/contacts/${params.id}`);
      } else {
        const created = await api.post('/api/contacts/', data);
        push(`/contacts/${created.contact_id}`);
      }
    } catch (e) {
      errors = e.data ? JSON.stringify(e.data) : e.message;
    }
  }

  function handleCancel() {
    if (isEdit) {
      push(`/contacts/${params.id}`);
    } else {
      push('/contacts');
    }
  }

  $effect(() => {
    load();
  });
</script>

<h2>{isEdit ? 'Edit Contact' : 'New Contact'}</h2>

{#if loading}
  <p>Loading...</p>
{:else}
  <ContactForm
    {contact}
    {businesses}
    {errors}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
```

**Step 3: Add routes to App.svelte**

```js
import ContactFormPage from './routes/contacts/ContactFormPage.svelte';

// Add to routes:
'/contacts/new': ContactFormPage,
'/contacts/:id/edit': ContactFormPage,
```

Note: `/contacts/new` must come BEFORE `/contacts/:id` in the routes object so it doesn't match as an id.

**Step 4: Verify**

- Navigate to `/#/contacts/new` — should show empty form, create contact, redirect to detail
- Navigate to `/#/contacts/1/edit` — should show pre-filled form, save changes, redirect to detail

**Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add contact create and edit form"
```

---

### Task 7: Business List

**Files:**
- Create: `frontend/shared/components/contacts/BusinessList.svelte`
- Create: `frontend/full/src/routes/contacts/BusinessListPage.svelte`
- Modify: `frontend/full/src/App.svelte` (add route)

**API endpoint:** `GET /api/businesses/` → paginated list with `{ business_id, our_reference_code, business_name, business_address, business_phone, tax_exemption_number, website, terms, default_contact, tax_multiplier }`

**Step 1: Create shared BusinessList component**

```svelte
<script>
  const { businesses = [], onSelect = null } = $props();
</script>

{#if businesses.length === 0}
  <p>No businesses found.</p>
{:else}
  <table border="1">
    <thead>
      <tr>
        <th>Reference</th>
        <th>Name</th>
        <th>Phone</th>
      </tr>
    </thead>
    <tbody>
      {#each businesses as business}
        <tr>
          <td>{business.our_reference_code}</td>
          <td>
            {#if onSelect}
              <a href="#" onclick={(e) => { e.preventDefault(); onSelect(business); }}>
                {business.business_name}
              </a>
            {:else}
              {business.business_name}
            {/if}
          </td>
          <td>{business.business_phone || ''}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
```

**Step 2: Create route page component**

Follow same pattern as ContactListPage — fetch from `/api/businesses/`, paginate, navigate on select.

```svelte
<script>
  import { api } from '$shared/lib/api.js';
  import BusinessList from '$shared/components/contacts/BusinessList.svelte';
  import { push } from 'svelte-spa-router';

  let businesses = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);

  async function loadBusinesses() {
    loading = true;
    error = null;
    try {
      const data = await api.get(`/api/businesses/?page=${page}`);
      businesses = data.results;
      count = data.count;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function handleSelect(business) {
    push(`/businesses/${business.business_id}`);
  }

  $effect(() => {
    loadBusinesses();
  });
</script>

<h2>Businesses ({count})</h2>

<p><a href="#/businesses/new">New Business</a></p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else}
  <BusinessList {businesses} onSelect={handleSelect} />

  {#if count > 25}
    <p>
      {#if page > 1}
        <button onclick={() => { page--; }}>Previous</button>
      {/if}
      Page {page}
      {#if page * 25 < count}
        <button onclick={() => { page++; }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}
```

**Step 3: Add route to App.svelte**

```js
import BusinessListPage from './routes/contacts/BusinessListPage.svelte';

// Add to routes:
'/businesses': BusinessListPage,
```

**Step 4: Verify**

Navigate to `/#/businesses` — should show paginated list.

**Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add business list page"
```

---

### Task 8: Business Detail

**Files:**
- Create: `frontend/shared/components/contacts/BusinessDetail.svelte`
- Create: `frontend/full/src/routes/contacts/BusinessDetailPage.svelte`
- Modify: `frontend/full/src/App.svelte` (add route)

**API endpoints:**
- `GET /api/businesses/{id}/`
- `DELETE /api/businesses/{id}/` → `{ confirm_required, impact: { jobs, purchase_orders, bills, contacts } }`
- `DELETE /api/businesses/{id}/?confirm=true` → 204
- `POST /api/businesses/{id}/set-default-contact/` with `{ contact_id }`

**Step 1: Create shared BusinessDetail component**

```svelte
<script>
  const { business, onEdit = null, onDelete = null } = $props();
</script>

<dl>
  <dt>Reference Code</dt>
  <dd>{business.our_reference_code}</dd>

  <dt>Name</dt>
  <dd>{business.business_name}</dd>

  {#if business.business_phone}
    <dt>Phone</dt>
    <dd>{business.business_phone}</dd>
  {/if}

  {#if business.business_address}
    <dt>Address</dt>
    <dd>{business.business_address}</dd>
  {/if}

  {#if business.website}
    <dt>Website</dt>
    <dd>{business.website}</dd>
  {/if}

  {#if business.tax_exemption_number}
    <dt>Tax Exemption</dt>
    <dd>{business.tax_exemption_number}</dd>
  {/if}

  <dt>Tax Multiplier</dt>
  <dd>{business.tax_multiplier ?? 'Default (full rate)'}</dd>

  <dt>Payment Terms</dt>
  <dd>{business.terms || 'None'}</dd>

  <dt>Default Contact</dt>
  <dd>{business.default_contact || 'None'}</dd>
</dl>

<p>
  {#if onEdit}
    <button onclick={onEdit}>Edit</button>
  {/if}
  {#if onDelete}
    <button onclick={onDelete}>Delete</button>
  {/if}
</p>
```

**Step 2: Create route page component**

Follow same pattern as ContactDetailPage — two-step delete, but show richer impact info (jobs, POs, bills, contacts).

```svelte
<script>
  import { api } from '$shared/lib/api.js';
  import BusinessDetail from '$shared/components/contacts/BusinessDetail.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let business = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let deleteConfirm = $state(null);

  async function loadBusiness() {
    loading = true;
    error = null;
    try {
      business = await api.get(`/api/businesses/${params.id}/`);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleDelete() {
    if (!deleteConfirm) {
      try {
        const result = await api.delete(`/api/businesses/${params.id}/`);
        if (result && result.confirm_required) {
          deleteConfirm = result.impact;
        }
      } catch (e) {
        error = e.message;
      }
      return;
    }

    try {
      await api.delete(`/api/businesses/${params.id}/?confirm=true`);
      push('/businesses');
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    loadBusiness();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if business}
  <h2>{business.business_name}</h2>
  <BusinessDetail
    {business}
    onEdit={() => push(`/businesses/${params.id}/edit`)}
    onDelete={handleDelete}
  />

  {#if deleteConfirm}
    <p>
      <strong>Are you sure?</strong> This business is associated with:
      {deleteConfirm.jobs} job(s),
      {deleteConfirm.purchase_orders} PO(s),
      {deleteConfirm.bills} bill(s),
      {deleteConfirm.contacts} contact(s).
      <button onclick={handleDelete}>Yes, delete</button>
      <button onclick={() => { deleteConfirm = null; }}>Cancel</button>
    </p>
  {/if}

  <p><a href="#/businesses">Back to list</a></p>
{/if}
```

**Step 3: Add route to App.svelte**

```js
import BusinessDetailPage from './routes/contacts/BusinessDetailPage.svelte';

// Add to routes:
'/businesses/:id': BusinessDetailPage,
```

**Step 4: Verify**

Navigate to `/#/businesses`, click a business → should show detail. Delete should show impact confirmation.

**Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add business detail page with delete confirmation"
```

---

### Task 9: Business Form (create + edit)

**Files:**
- Create: `frontend/shared/components/contacts/BusinessForm.svelte`
- Create: `frontend/full/src/routes/contacts/BusinessFormPage.svelte`
- Modify: `frontend/full/src/App.svelte` (add routes)

**API endpoints:**
- `POST /api/businesses/` with `{ business_name, ... }`
- `PATCH /api/businesses/{id}/` with changed fields
- `GET /api/payment-terms/` → unpaginated list for dropdown
- `GET /api/contacts/?page_size=100` → for default_contact dropdown

**Step 1: Create shared BusinessForm component**

```svelte
<script>
  const {
    business = null,
    paymentTerms = [],
    contacts = [],
    onSubmit,
    onCancel,
    errors = null,
  } = $props();

  let form = $state({
    business_name: business?.business_name || '',
    business_address: business?.business_address || '',
    business_phone: business?.business_phone || '',
    tax_exemption_number: business?.tax_exemption_number || '',
    website: business?.website || '',
    tax_multiplier: business?.tax_multiplier ?? '',
    terms: business?.terms || '',
    default_contact: business?.default_contact || '',
  });

  function handleSubmit(e) {
    e.preventDefault();
    const data = { ...form };
    if (data.terms === '') data.terms = null;
    if (data.default_contact === '') data.default_contact = null;
    if (data.tax_multiplier === '') data.tax_multiplier = null;
    onSubmit(data);
  }
</script>

<form onsubmit={handleSubmit}>
  {#if errors}
    <p><strong>Error:</strong> {errors}</p>
  {/if}

  <p>
    <label for="business_name"><strong>Business Name *</strong></label><br>
    <input type="text" id="business_name" bind:value={form.business_name} required>
  </p>
  <p>
    <label for="business_phone"><strong>Phone</strong></label><br>
    <input type="text" id="business_phone" bind:value={form.business_phone}>
  </p>
  <p>
    <label for="business_address"><strong>Address</strong></label><br>
    <textarea id="business_address" bind:value={form.business_address}></textarea>
  </p>
  <p>
    <label for="website"><strong>Website</strong></label><br>
    <input type="url" id="website" bind:value={form.website}>
  </p>

  <fieldset>
    <legend><strong>Tax</strong></legend>
    <p>
      <label for="tax_exemption_number"><strong>Tax Exemption Number</strong></label><br>
      <input type="text" id="tax_exemption_number" bind:value={form.tax_exemption_number}>
    </p>
    <p>
      <label for="tax_multiplier"><strong>Tax Multiplier</strong></label><br>
      <input type="number" id="tax_multiplier" bind:value={form.tax_multiplier} step="0.01" min="0" max="1">
    </p>
  </fieldset>

  <p>
    <label for="terms"><strong>Payment Terms</strong></label><br>
    <select id="terms" bind:value={form.terms}>
      <option value="">-- None --</option>
      {#each paymentTerms as term}
        <option value={term.term_id}>{term.term_id}</option>
      {/each}
    </select>
  </p>

  <p>
    <label for="default_contact"><strong>Default Contact</strong></label><br>
    <select id="default_contact" bind:value={form.default_contact}>
      <option value="">-- None --</option>
      {#each contacts as c}
        <option value={c.contact_id}>{c.name}</option>
      {/each}
    </select>
  </p>

  <p>
    <button type="submit">{business ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>
```

**Step 2: Create route page component**

```svelte
<script>
  import { api } from '$shared/lib/api.js';
  import BusinessForm from '$shared/components/contacts/BusinessForm.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let business = $state(null);
  let paymentTerms = $state([]);
  let contacts = $state([]);
  let loading = $state(true);
  let errors = $state(null);

  async function load() {
    loading = true;
    try {
      const [termsData, contactsData] = await Promise.all([
        api.get('/api/payment-terms/'),
        api.get('/api/contacts/?page_size=100'),
      ]);
      paymentTerms = termsData;
      contacts = contactsData.results;

      if (isEdit) {
        business = await api.get(`/api/businesses/${params.id}/`);
      }
    } catch (e) {
      errors = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(data) {
    errors = null;
    try {
      if (isEdit) {
        await api.patch(`/api/businesses/${params.id}/`, data);
        push(`/businesses/${params.id}`);
      } else {
        const created = await api.post('/api/businesses/', data);
        push(`/businesses/${created.business_id}`);
      }
    } catch (e) {
      errors = e.data ? JSON.stringify(e.data) : e.message;
    }
  }

  function handleCancel() {
    if (isEdit) {
      push(`/businesses/${params.id}`);
    } else {
      push('/businesses');
    }
  }

  $effect(() => {
    load();
  });
</script>

<h2>{isEdit ? 'Edit Business' : 'New Business'}</h2>

{#if loading}
  <p>Loading...</p>
{:else}
  <BusinessForm
    {business}
    {paymentTerms}
    {contacts}
    {errors}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
```

**Step 3: Add routes to App.svelte**

```js
import BusinessFormPage from './routes/contacts/BusinessFormPage.svelte';

// Add to routes (before /:id):
'/businesses/new': BusinessFormPage,
'/businesses/:id/edit': BusinessFormPage,
```

**Step 4: Verify**

- `/#/businesses/new` — empty form, create, redirect
- `/#/businesses/1/edit` — pre-filled form, save, redirect

**Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add business create and edit form"
```

---

### Task 10: Final wiring — complete App.svelte routes

**Files:**
- Modify: `frontend/full/src/App.svelte`

**Step 1: Assemble final App.svelte with all routes in correct order**

```svelte
<script>
  import Router from 'svelte-spa-router';
  import Nav from './components/Nav.svelte';
  import Home from './routes/Home.svelte';
  import ContactListPage from './routes/contacts/ContactListPage.svelte';
  import ContactFormPage from './routes/contacts/ContactFormPage.svelte';
  import ContactDetailPage from './routes/contacts/ContactDetailPage.svelte';
  import BusinessListPage from './routes/contacts/BusinessListPage.svelte';
  import BusinessFormPage from './routes/contacts/BusinessFormPage.svelte';
  import BusinessDetailPage from './routes/contacts/BusinessDetailPage.svelte';

  const routes = {
    '/': Home,
    '/contacts': ContactListPage,
    '/contacts/new': ContactFormPage,
    '/contacts/:id/edit': ContactFormPage,
    '/contacts/:id': ContactDetailPage,
    '/businesses': BusinessListPage,
    '/businesses/new': BusinessFormPage,
    '/businesses/:id/edit': BusinessFormPage,
    '/businesses/:id': BusinessDetailPage,
  };
</script>

<h1>Minibini</h1>
<Nav />
<Router {routes} />
```

Route order matters: `/new` and `/:id/edit` must come before `/:id` so they don't match as an id param.

**Step 2: Verify all routes end-to-end**

Run both Django and Vite. Test the full flow:
1. `http://localhost:9000` → Home
2. `/#/contacts` → Contact list with pagination
3. `/#/contacts/new` → Create contact → redirects to detail
4. `/#/contacts/1` → Contact detail
5. `/#/contacts/1/edit` → Edit contact → redirects to detail
6. Contact delete with confirmation
7. `/#/businesses` → Business list with pagination
8. `/#/businesses/new` → Create business
9. `/#/businesses/1` → Business detail
10. `/#/businesses/1/edit` → Edit business
11. Business delete with confirmation

**Step 3: Commit**

```bash
git add frontend/full/src/App.svelte
git commit -m "feat: wire up all contact and business routes"
```
