# Inputs-to-Modals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every YES-marked non-modal input surface in `docs/plans/2026-10-10-inputs-to-modals-inventory.md` into the shared `Modal.svelte` shell, opening over the page the user is on, with create-saves navigating to the new record's detail page.

**Architecture:** Each full-page form becomes a `<X>Modal.svelte` component that owns its own load/submit/error state (the `JobEditModal` shape), hosted wherever the old link lived; the old route becomes a `RedirectTo` stub. Duplicate-detection becomes an in-modal sub-state (the form stays mounted but `hidden` behind a notice fragment; Escape backs out one level). Inline show/hide forms on list/detail pages are wrapped in `<Modal>` in place. The send step is one `DocumentSendModal` mounted beside each document panel. Password changes move behind a button into their own modals with the `autocomplete="username"` fix.

**Tech Stack:** Svelte 5 runes, `svelte-spa-router` (`wrap` for route props), Vitest + `@testing-library/svelte` (`frontend/tests/`), Playwright (`e2e/`). No backend changes.

**Spec:** `docs/plans/2026-10-10-inputs-to-modals-inventory.md` (the decision table + the three cross-cutting decisions at the bottom).

**Branch:** all work commits to `feature/ui`. Never push, merge, or open a PR.

## Global Constraints

- **No backend changes.** Every task is frontend-only; the Django suite is not part of this plan's verification.
- **Modal shell contract** (`frontend/README.md` → Modals): every modal rides `components/Modal.svelte`, passes `onCancel` (Escape closes), passes a `label` (the e2e specs scope by `getByRole('dialog', { name })`), and is a native `<form onsubmit>` with a `type="submit"` save button and `type="button"` on every other button — omit `onSave` for native forms. Button-driven modals (no `<form>`) pass `onSave` and `busy`.
- **Sub-state modals** pass an `onCancel` that backs out one level (clear the notice) before closing.
- **Links navigate; buttons act.** Every `<a href="#/…/new">` / `#/…/send` becomes a `<button type="button">`.
- **Create-save navigates** to the new record's detail page via `push()`; **edit-save stays** and refreshes the host; **cancel stays**.
- **Prefill context** moves from query strings to props (`defaultContactId`, `defaultBusinessId`).
- **Error contract:** route every submit error through `triageError(e)` → `FieldError` / `FormMessage` / `showError`. Never `alert()`, never bare `e.message` in new code (existing pages that already use `fieldErrors(errors, ...)` keep their shape when ported).
- **Confirmations only for the irreversible:** the existing `confirm()` in `DocumentSendForm` and the invoice deposit-credit confirm stay. No confirm on cancel/close.
- **Tests per task:** Vitest for every new/changed component (`cd frontend && npx vitest run <file>`), plus the named e2e spec (`cd e2e && npx playwright test <spec>`), in the same commit. Only one Playwright run at a time.
- **Parked (do not touch):** `PurchaseOrderFormPage`, `PurchaseOrderSendPage`, `LineItemForm`, `ReceiveItemsForm`, `ReconciliationSection`, `PurchaseOrderDetail` inline edit, `EmailCreatePOPage` and its `create-po` link. `DuplicateContactModal` / `DuplicateBusinessModal` files stay (as thin wrappers) because `EmailCreatePOPage` still uses them.
- **Commit messages** end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Docs:** `docs/designs/*` and `frontend/README.md` are updated in Task 17, the ui-flows checklists alongside.

## Review Focus

1. **Escape while a duplicate notice is showing** must return to the still-filled form, not close the modal. (Task 2 test: "Escape backs out of the duplicate notice".)
2. **Reopening a create modal** after a cancelled or failed attempt must show a clean form (no stale values, no stale `FieldError`s). (Task 2 test: "reopening shows a clean form".)
3. **Declining the invoice deposit-credit confirm** must leave the send modal open with the typed recipient intact, and must not POST. (Task 7 test on `DocumentSendModal`: "beforeSubmit false aborts without posting".)
4. **Edit-save refreshes the host page without navigating** (contact/business detail). (Task 2 test on `ContactDetailPage`: "edit save reloads the contact and stays".)
5. **Permission gating of the new buttons:** the old pages rendered "You do not have permission" for non-managers; the buttons must simply not render. (Task 4 `NewJobButton` test "renders nothing without can_manage_jobs" kept; Task 2 `ContactListPage` test "hides New Contact without can_manage_jobs".)

---

### Task 1: Shared pieces — `RedirectTo` route stub and the duplicate-notice fragments

**Files:**
- Create: `frontend/src/routes/RedirectTo.svelte`
- Create: `frontend/src/components/contacts/DuplicateContactNotice.svelte`
- Create: `frontend/src/components/contacts/DuplicateBusinessNotice.svelte`
- Modify: `frontend/src/components/contacts/DuplicateContactModal.svelte` (becomes a wrapper)
- Modify: `frontend/src/components/contacts/DuplicateBusinessModal.svelte` (becomes a wrapper)
- Test: `frontend/tests/routes/RedirectTo.test.js`, `frontend/tests/components/contacts/DuplicateContactNotice.test.js`

**Interfaces:**
- Produces `RedirectTo` — props `{ params, to }`; `to` is a hash path with `:name` placeholders substituted from `params` (e.g. `'/contacts/:id'`). Used in `App.svelte` as `wrap({ component: RedirectTo, props: { to: '…' } })`.
- Produces `DuplicateContactNotice` — props `{ contact, onViewExisting, onBack }`; `DuplicateBusinessNotice` — props `{ business, onViewExisting, onBack }`. Plain fragments, no `<Modal>`.
- The two `Duplicate*Modal` components keep their exact prop signatures (`open, contact|business, onViewExisting, onClose`) so `EmailCreatePOPage` is untouched.

- [ ] **Step 1: Write the failing tests**

`frontend/tests/routes/RedirectTo.test.js`:
```js
import { describe, it, expect, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import RedirectTo from '@/routes/RedirectTo.svelte';

beforeEach(() => { window.location.hash = '#/somewhere'; });

describe('RedirectTo', () => {
  it('replaces the hash with the target, substituting :params', async () => {
    render(RedirectTo, { props: { params: { id: '42' }, to: '/contacts/:id' } });
    await waitFor(() => expect(window.location.hash).toBe('#/contacts/42'));
  });

  it('works with no params', async () => {
    render(RedirectTo, { props: { to: '/contacts' } });
    await waitFor(() => expect(window.location.hash).toBe('#/contacts'));
  });
});
```

`frontend/tests/components/contacts/DuplicateContactNotice.test.js`:
```js
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import DuplicateContactNotice from '@/components/contacts/DuplicateContactNotice.svelte';

const CONTACT = { contact_id: 3, name: 'Casey Contact', email: 'c@example.com' };

describe('DuplicateContactNotice', () => {
  it('shows the existing contact and wires both buttons', async () => {
    const onViewExisting = vi.fn();
    const onBack = vi.fn();
    const { getByText, getByRole } = render(DuplicateContactNotice, {
      props: { contact: CONTACT, onViewExisting, onBack },
    });
    expect(getByText('This contact may already exist')).toBeInTheDocument();
    expect(getByText('Casey Contact')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'View Existing Contact' }));
    expect(onViewExisting).toHaveBeenCalled();
    await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
    expect(onBack).toHaveBeenCalled();
  });

  it('renders no dialog of its own (it is a fragment for a host modal)', () => {
    const { queryByRole } = render(DuplicateContactNotice, { props: { contact: CONTACT } });
    expect(queryByRole('dialog')).toBeNull();
  });
});
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `cd frontend && npx vitest run tests/routes/RedirectTo.test.js tests/components/contacts/DuplicateContactNotice.test.js`
Expected: FAIL — cannot resolve `@/routes/RedirectTo.svelte` / `DuplicateContactNotice.svelte`.

- [ ] **Step 3: Write `RedirectTo.svelte`**

```svelte
<script>
  // Route stub for pages that became modals (contact/business/job/user
  // create, email create-job/link, document send). A stale bookmark or
  // deep link lands here and bounces to the host page, where the button
  // that opens the modal lives. Mirrors routes/jobs/JobRedirectToOverview.
  //
  // `to` is a hash path; `:name` segments are filled from the route params
  // (svelte-spa-router passes `params` alongside wrap()'s `props`).
  let { params = {}, to = '/' } = $props();

  $effect(() => {
    const target = to.replace(/:([A-Za-z]+)/g, (_, key) => params?.[key] ?? '');
    window.location.replace(`#${target}`);
  });
</script>

<p>Redirecting…</p>
```

- [ ] **Step 4: Write the two notice fragments**

`DuplicateContactNotice.svelte`:
```svelte
<script>
  // The duplicate-detection SUB-STATE of a create modal (RM 2026-10-10:
  // sub-state, not a stacked modal). The host renders this in place of its
  // form while keeping the form mounted-but-hidden, so "Go Back and Edit"
  // returns to every value the user typed. No <Modal> here — the host owns
  // the shell and backs out one level on Escape.
  const {
    contact = null,
    onViewExisting = () => {},
    onBack = () => {},
  } = $props();
</script>

<h3 class="dup-title">This contact may already exist</h3>

{#if contact}
  <p>A contact with this email address is already in the system:</p>
  <p>
    <strong>{contact.name}</strong><br>
    {contact.email}<br>
    {#if contact.mobile_number || contact.work_number || contact.home_number}
      {contact.mobile_number || contact.work_number || contact.home_number}<br>
    {/if}
    {#if contact.business}
      {contact.business.business_name}
    {/if}
  </p>
{/if}

<p>
  <button type="button" onclick={onViewExisting}>View Existing Contact</button>
  <button type="button" onclick={onBack}>Go Back and Edit</button>
</p>

<style>
  .dup-title { margin: 0 0 12px; font-size: 16px; }
</style>
```

`DuplicateBusinessNotice.svelte` — identical shape with `business`, heading "This business may already exist", body "A business with this name is already in the system:", `business.business_name` / `our_reference_code` / `business_phone` lines as in the current `DuplicateBusinessModal`, and buttons "View Existing Business" / "Go Back and Edit".

- [ ] **Step 5: Turn the two Duplicate*Modal files into wrappers**

`DuplicateContactModal.svelte` (whole file):
```svelte
<script>
  // Thin wrapper kept for EmailCreatePOPage (PO process is parked). The
  // create modals render DuplicateContactNotice directly as a sub-state.
  // Esc-only: both actions are navigation, no single confirm — no onSave.
  import Modal from '../Modal.svelte';
  import DuplicateContactNotice from './DuplicateContactNotice.svelte';

  const {
    open = false,
    contact = null,
    onViewExisting = () => {},
    onClose = () => {},
  } = $props();
</script>

<Modal {open} onCancel={onClose} maxWidth="500px" label="Possible duplicate contact">
  <DuplicateContactNotice {contact} {onViewExisting} onBack={onClose} />
</Modal>
```
Same for `DuplicateBusinessModal.svelte` with `DuplicateBusinessNotice` and label "Possible duplicate business".

- [ ] **Step 6: Run the tests (new + the existing duplicate-modal consumers)**

Run: `cd frontend && npx vitest run tests/routes/RedirectTo.test.js tests/components/contacts tests/components/email`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/RedirectTo.svelte frontend/src/components/contacts/Duplicate*.svelte frontend/tests/routes/RedirectTo.test.js frontend/tests/components/contacts/DuplicateContactNotice.test.js
git commit -m "feat(ui): RedirectTo route stub + duplicate-detection notice fragments

Groundwork for moving page forms into modals: a generic redirect stub for
retired routes, and the duplicate contact/business prompts as plain
fragments so a create modal can show them as a sub-state instead of
stacking a second modal.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Contact create/edit → `ContactFormModal` (A1)

**Files:**
- Create: `frontend/src/components/contacts/ContactFormModal.svelte`
- Modify: `frontend/src/components/contacts/ContactForm.svelte` (drop the unused `businesses` prop)
- Modify: `frontend/src/routes/contacts/ContactListPage.svelte:150` (New Contact link → button + modal)
- Modify: `frontend/src/routes/contacts/ContactDetailPage.svelte:95` (Edit → modal)
- Modify: `frontend/src/components/contacts/BusinessDetail.svelte:96` (New Contact link → button + modal)
- Modify: `frontend/src/App.svelte` (routes `/contacts/new`, `/contacts/:id/edit` → `RedirectTo`)
- Delete: `frontend/src/routes/contacts/ContactFormPage.svelte`
- Test: `frontend/tests/components/contacts/ContactFormModal.test.js` (new), update `ContactForm.test.js` if it passes `businesses`, `ContactListPage.test.js`, `ContactDetailPage.test.js`, `BusinessDetail.test.js`
- E2E: `e2e/specs/contacts/contact-modal.spec.js` (new)

**Interfaces:**
- Produces `ContactFormModal` — props `{ open, contact = null, defaultBusinessId = null, onSaved = (contact) => {}, onClose }`. `contact` null = create (navigates to the new contact on success); object = edit (calls `onSaved(updated)`, host closes + reloads).

- [ ] **Step 1: Write the failing Vitest file**

`frontend/tests/components/contacts/ContactFormModal.test.js`:
```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import ContactFormModal from '@/components/contacts/ContactFormModal.svelte';

beforeEach(() => {
  push.mockReset();
  api.get.mockReset(); api.post.mockReset(); api.patch.mockReset();
  api.get.mockResolvedValue({ results: [] }); // BusinessPicker search
});

async function fillRequired(getByLabelText) {
  await fireEvent.input(getByLabelText(/First Name/), { target: { value: 'Casey' } });
  await fireEvent.input(getByLabelText(/Last Name/), { target: { value: 'Contact' } });
  await fireEvent.input(getByLabelText(/Email/), { target: { value: 'c@example.com' } });
}

describe('ContactFormModal — create', () => {
  it('posts and navigates to the new contact', async () => {
    api.post.mockResolvedValue({ contact_id: 9 });
    const onClose = vi.fn();
    const { getByLabelText, getByRole } = render(ContactFormModal, { props: { open: true, onClose } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/contacts/', expect.objectContaining({ email: 'c@example.com' })));
    expect(onClose).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/contacts/9');
  });

  it('seeds the business from defaultBusinessId', async () => {
    api.post.mockResolvedValue({ contact_id: 9 });
    const { getByLabelText, getByRole } = render(ContactFormModal, { props: { open: true, defaultBusinessId: 4 } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/contacts/', expect.objectContaining({ business_id: 4 })));
  });

  it('shows the duplicate notice as a sub-state and keeps the typed values behind it', async () => {
    api.post.mockRejectedValue({ status: 409, data: { code: 'duplicate_email', existing_contact: { contact_id: 3, name: 'Casey Contact', email: 'c@example.com' } } });
    const { getByLabelText, getByRole, findByText, queryByRole } = render(ContactFormModal, { props: { open: true } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    expect(await findByText('This contact may already exist')).toBeInTheDocument();
    // Still ONE dialog — the notice is a sub-state, not a second modal.
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(1);
    expect(queryByRole('button', { name: 'Create' })).toBeNull(); // form hidden
    await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
    expect(getByLabelText(/First Name/).value).toBe('Casey');
  });

  it('Escape backs out of the duplicate notice instead of closing', async () => {
    api.post.mockRejectedValue({ status: 409, data: { code: 'duplicate_email', existing_contact: { contact_id: 3, name: 'X', email: 'c@example.com' } } });
    const onClose = vi.fn();
    const { getByLabelText, getByRole, findByText } = render(ContactFormModal, { props: { open: true, onClose } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await findByText('This contact may already exist');
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    expect(getByLabelText(/First Name/).value).toBe('Casey');
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('View Existing Contact closes and navigates', async () => {
    api.post.mockRejectedValue({ status: 409, data: { code: 'duplicate_email', existing_contact: { contact_id: 3, name: 'X', email: 'c@example.com' } } });
    const onClose = vi.fn();
    const { getByLabelText, getByRole, findByRole } = render(ContactFormModal, { props: { open: true, onClose } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await fireEvent.click(await findByRole('button', { name: 'View Existing Contact' }));
    expect(onClose).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/contacts/3');
  });

  it('renders field errors under inputs', async () => {
    api.post.mockRejectedValue({ status: 400, data: { email: ['Enter a valid email address.'] } });
    const { getByLabelText, getByRole, findByText } = render(ContactFormModal, { props: { open: true } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    expect(await findByText('Enter a valid email address.')).toBeInTheDocument();
  });

  it('reopening shows a clean form', async () => {
    api.post.mockRejectedValue({ status: 400, data: { email: ['Bad.'] } });
    const { getByLabelText, getByRole, findByText, rerender, queryByText } = render(ContactFormModal, { props: { open: true } });
    await fillRequired(getByLabelText);
    await fireEvent.click(getByRole('button', { name: 'Create' }));
    await findByText('Bad.');
    await rerender({ open: false });
    await rerender({ open: true });
    expect(queryByText('Bad.')).toBeNull();
    expect(getByLabelText(/First Name/).value).toBe('');
  });
});

describe('ContactFormModal — edit', () => {
  const CONTACT = { contact_id: 5, first_name: 'Old', last_name: 'Name', email: 'o@example.com', business: null };

  it('prefills, patches and calls onSaved without navigating', async () => {
    api.patch.mockResolvedValue({ ...CONTACT, first_name: 'New' });
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(ContactFormModal, { props: { open: true, contact: CONTACT, onSaved } });
    expect(getByLabelText(/First Name/).value).toBe('Old');
    await fireEvent.input(getByLabelText(/First Name/), { target: { value: 'New' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/contacts/5/', expect.objectContaining({ first_name: 'New' })));
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ first_name: 'New' }));
    expect(push).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run tests/components/contacts/ContactFormModal.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `ContactFormModal.svelte`**

```svelte
<script>
  // Contact create/edit, hosted in Modal (replaces routes/contacts/
  // ContactFormPage.svelte, 2026-10-10). Opens over whatever page the user
  // is on: the contacts list, a contact's own detail page (edit), or a
  // business page (new contact pre-attached to that business).
  //
  // Duplicate detection is a SUB-STATE: on a 409 duplicate_email the form
  // stays mounted but hidden and DuplicateContactNotice renders in its
  // place; Escape / "Go Back and Edit" return to the form with every typed
  // value intact. Escape again closes. (No stacked modal — RM 2026-10-10.)
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import ContactForm from './ContactForm.svelte';
  import DuplicateContactNotice from './DuplicateContactNotice.svelte';

  let {
    open = false,
    contact = null,            // null → create; detail object → edit
    defaultBusinessId = null,  // create only: pre-attach to this business
    onSaved = () => {},        // edit only: (updatedContact)
    onClose = () => {},
  } = $props();

  const isEdit = $derived(!!contact);

  let formError = $state('');
  let fieldErrs = $state({});
  let duplicateContact = $state(null);

  // Fresh messages on every open. (Modal unmounts its children when closed,
  // so ContactForm's own state re-seeds on the next open by itself.)
  $effect(() => {
    if (open) { formError = ''; fieldErrs = {}; duplicateContact = null; }
  });

  async function handleSubmit(data) {
    formError = '';
    fieldErrs = {};
    duplicateContact = null;
    try {
      if (isEdit) {
        const updated = await api.patch(`/api/contacts/${contact.contact_id}/`, data);
        onSaved(updated);
      } else {
        const created = await api.post('/api/contacts/', data);
        onClose();
        push(`/contacts/${created.contact_id}`);
      }
    } catch (e) {
      if (!isEdit && e.status === 409 && e.data?.code === 'duplicate_email') {
        duplicateContact = e.data.existing_contact;
        return;
      }
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { formError = t.message; fieldErrs = t.fields; }
    }
  }

  // Escape backs out one level: notice → form → closed.
  function handleCancel() {
    if (duplicateContact) duplicateContact = null;
    else onClose();
  }

  function viewExisting() {
    const id = duplicateContact.contact_id;
    onClose();
    push(`/contacts/${id}`);
  }
</script>

<!-- Enter is owned by ContactForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={handleCancel} maxWidth="640px" label={isEdit ? 'Edit contact' : 'New contact'}>
  <h3 class="modal-title">{isEdit ? 'Edit Contact' : 'New Contact'}</h3>

  {#if duplicateContact}
    <DuplicateContactNotice
      contact={duplicateContact}
      onViewExisting={viewExisting}
      onBack={() => { duplicateContact = null; }}
    />
  {/if}

  <!-- hidden, not {#if}: the form must survive the notice round-trip. -->
  <div hidden={!!duplicateContact}>
    <ContactForm
      {contact}
      {defaultBusinessId}
      errors={fieldErrs}
      {formError}
      onSubmit={handleSubmit}
      onCancel={onClose}
    />
  </div>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
```

- [ ] **Step 4: Drop the dead `businesses` prop from `ContactForm.svelte`**

Remove the `businesses = [],` line from the `$props()` destructure (it is never read — `BusinessPicker` searches on its own). Grep `tests/components/contacts/ContactForm.test.js` for `businesses` and remove the prop from any `render(..., { props })` call.

- [ ] **Step 5: Run the modal test**

Run: `cd frontend && npx vitest run tests/components/contacts/ContactFormModal.test.js tests/components/contacts/ContactForm.test.js`
Expected: PASS.

- [ ] **Step 6: Host it — `ContactListPage.svelte`**

Replace line 150:
```svelte
<p><a href="#/contacts/new">New Contact</a> &nbsp; <a href="#/businesses/new">New Business</a></p>
```
with (the New Business half is Task 3; leave its `<a>` for now):
```svelte
<p>
  {#if $canManageJobs}
    <button type="button" onclick={() => { newContactOpen = true; }}>New Contact</button>
  {/if}
  &nbsp; <a href="#/businesses/new">New Business</a>
</p>
<ContactFormModal open={newContactOpen} onClose={() => { newContactOpen = false; }} />
```
In the script add:
```js
import { canManageJobs } from '../../stores/permissions.js';
import ContactFormModal from '../../components/contacts/ContactFormModal.svelte';
let newContactOpen = $state(false);
```

Add to `tests/components/contacts/ContactListPage.test.js` (follow the file's existing `user.set` / mock pattern):
```js
it('offers New Contact as a button to a jobs manager and opens the modal', async () => {
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
  const { findByRole, queryByRole } = render(ContactListPage);
  const btn = await findByRole('button', { name: 'New Contact' });
  expect(queryByRole('link', { name: 'New Contact' })).toBeNull();
  await fireEvent.click(btn);
  expect(await findByRole('dialog', { name: 'New contact' })).toBeInTheDocument();
});

it('hides New Contact without can_manage_jobs', async () => {
  user.set({ id: 2, permissions: [] });
  const { findByRole, queryByRole } = render(ContactListPage);
  await findByRole('heading', { name: /Contacts/ });
  expect(queryByRole('button', { name: 'New Contact' })).toBeNull();
});
```
(If the test file does not already import `user` from `@/stores/auth.js` and `fireEvent`, add them.)

- [ ] **Step 7: Host it — `ContactDetailPage.svelte` (edit)**

Script: import `ContactFormModal`, add `let editOpen = $state(false);`. Change the `onEdit` prop to `onEdit={() => { editOpen = true; }}` and add inside the `{#if contact}` block, after `<ContactDetail … />`:
```svelte
<ContactFormModal
  open={editOpen}
  {contact}
  onSaved={() => { editOpen = false; loadContact(); }}
  onClose={() => { editOpen = false; }}
/>
```
Add to `tests/components/contacts/ContactDetailPage.test.js`:
```js
it('edit save reloads the contact and stays', async () => {
  // existing mock set-up for api.get('/api/contacts/1/') etc.
  api.patch.mockResolvedValue({ contact_id: 1, first_name: 'Renamed', last_name: 'Doe', email: 'j@example.com', name: 'Renamed Doe' });
  const { findByRole } = render(ContactDetailPage, { props: { params: { id: '1' } } });
  await fireEvent.click(await findByRole('button', { name: 'Edit' }));
  const dialog = await findByRole('dialog', { name: 'Edit contact' });
  await fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/contacts/1/', expect.any(Object)));
  // Reloaded, not navigated.
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(/* initial calls */ expect.any(Number)));
  expect(push).not.toHaveBeenCalledWith(expect.stringMatching(/\/edit$/));
  expect(api.get.mock.calls.filter((c) => c[0] === '/api/contacts/1/').length).toBeGreaterThanOrEqual(2);
});
```
(Replace the `toHaveBeenCalledTimes(expect.any(Number))` line with nothing — the last assertion is the real check; `api.patch` must be added to that file's `vi.mock('@/lib/api.js')` and `within` imported from `@testing-library/svelte`.)

- [ ] **Step 8: Host it — `BusinessDetail.svelte` (New Contact for this business)**

Replace line 96 `— <a href="#/contacts/new?business={business.business_id}">New Contact</a>` with
```svelte
— <button type="button" class="link-btn" onclick={() => { newContactOpen = true; }}>New Contact</button>
```
(`.link-btn` already exists app-wide for button-as-text; if this component lacks it, add `.link-btn { background:none; border:0; padding:0; color:#2563eb; cursor:pointer; font:inherit; }` to its `<style>`.) Keep whatever `{#if $canManageJobs}` guard currently wraps the line; if none wraps it, add one. Import `ContactFormModal`, add `let newContactOpen = $state(false);`, and render at the end of the component:
```svelte
<ContactFormModal open={newContactOpen} defaultBusinessId={business.business_id} onClose={() => { newContactOpen = false; }} />
```
Add to `tests/components/contacts/BusinessDetail.test.js`:
```js
it('New Contact opens the contact modal pre-attached to this business', async () => {
  const { findByRole } = render(BusinessDetail, { props: { business: BUSINESS, invoices: null, purchaseOrders: null, history: null } });
  await fireEvent.click(await findByRole('button', { name: 'New Contact' }));
  expect(await findByRole('dialog', { name: 'New contact' })).toBeInTheDocument();
});
```
(Use the file's existing `BUSINESS` fixture / props shape.)

- [ ] **Step 9: Routes and page deletion**

In `App.svelte`: add `import { wrap } from 'svelte-spa-router/wrap';` and `import RedirectTo from './routes/RedirectTo.svelte';`, remove the `ContactFormPage` import, and change:
```js
'/contacts/new': wrap({ component: RedirectTo, props: { to: '/contacts' } }),
'/contacts/:id/edit': wrap({ component: RedirectTo, props: { to: '/contacts/:id' } }),
```
Delete `frontend/src/routes/contacts/ContactFormPage.svelte`. Grep `frontend/src` and `frontend/tests` for `ContactFormPage` — there must be no remaining references.

- [ ] **Step 10: Run the contacts test folder and the build**

Run: `cd frontend && npx vitest run tests/components/contacts && npm run build`
Expected: all PASS, build succeeds.

- [ ] **Step 11: E2E spec**

`e2e/specs/contacts/contact-modal.spec.js`:
```js
// Contact create/edit moved from /contacts/new + /:id/edit pages into
// ContactFormModal (2026-10-10). The modal opens over the current page; a
// create lands on the new contact, an edit stays on the detail page, and
// duplicate detection is an in-modal sub-state.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-${Date.now().toString(36)}`;

test('list → New Contact modal → create lands on the contact; Edit stays; duplicate is a sub-state', async ({ page }) => {
  await page.goto('/#/contacts');
  await page.getByRole('button', { name: 'New Contact' }).click();
  const dialog = page.getByRole('dialog', { name: 'New contact' });
  await expect(dialog).toBeVisible();

  await test.step('create → navigates to the new contact', async () => {
    await dialog.getByLabel('First Name *').fill(stamp);
    await dialog.getByLabel('Last Name *').fill('Modal');
    await dialog.getByLabel('Email *').fill(`${stamp}@example.invalid`);
    await dialog.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/#\/contacts\/\d+$/);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByText(`${stamp} Modal`).first()).toBeVisible();
  });

  await test.step('Edit → save stays on the detail page', async () => {
    await page.getByRole('button', { name: 'Edit' }).click();
    const edit = page.getByRole('dialog', { name: 'Edit contact' });
    await edit.getByLabel('Last Name *').fill('Renamed');
    await edit.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page).toHaveURL(/#\/contacts\/\d+$/);
    await expect(page.getByText(`${stamp} Renamed`).first()).toBeVisible();
  });

  await test.step('duplicate email → notice inside the same modal → Go Back keeps the values', async () => {
    await page.goto('/#/contacts');
    await page.getByRole('button', { name: 'New Contact' }).click();
    const dup = page.getByRole('dialog', { name: 'New contact' });
    await dup.getByLabel('First Name *').fill('Dup');
    await dup.getByLabel('Last Name *').fill('Licate');
    await dup.getByLabel('Email *').fill(`${stamp}@example.invalid`);
    await dup.getByRole('button', { name: 'Create' }).click();
    await expect(dup.getByText('This contact may already exist')).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(1);
    await dup.getByRole('button', { name: 'Go Back and Edit' }).click();
    await expect(dup.getByLabel('First Name *')).toHaveValue('Dup');
    await dup.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });
});

test('a worker sees no New Contact button', async ({ page, browser }) => {
  const ctx = await browser.newContext({ storageState: personas.worker.storageState });
  const p = await ctx.newPage();
  await p.goto('/#/contacts');
  await expect(p.getByRole('heading', { name: /Contacts/ })).toBeVisible();
  await expect(p.getByRole('button', { name: 'New Contact' })).toHaveCount(0);
  await ctx.close();
});
```
Run: `cd e2e && npx playwright test specs/contacts/contact-modal.spec.js`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add -A frontend/src frontend/tests e2e/specs/contacts/contact-modal.spec.js
git commit -m "feat(contacts): contact create/edit opens in ContactFormModal over the current page

Replaces ContactFormPage. New Contact (list, business page) and Edit
(detail) are buttons; create lands on the new contact, edit reloads in
place. Duplicate-email detection is an in-modal sub-state. /contacts/new
and /:id/edit redirect to their host pages.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Business create/edit → `BusinessFormModal` (A2)

**Files:**
- Create: `frontend/src/components/contacts/BusinessFormModal.svelte`
- Modify: `ContactListPage.svelte` (New Business), `routes/contacts/BusinessListPage.svelte:40`, `routes/contacts/BusinessDetailPage.svelte:97`, `App.svelte`
- Delete: `frontend/src/routes/contacts/BusinessFormPage.svelte`
- Test: `frontend/tests/components/contacts/BusinessFormModal.test.js` (new); update `ContactListPage.test.js`, `BusinessDetailPage.test.js` (if present; else add a minimal one)
- E2E: `e2e/specs/contacts/business-modal.spec.js` (new); update `e2e/specs/settings/payment-terms.spec.js:42`

**Interfaces:**
- Produces `BusinessFormModal` — props `{ open, business = null, onSaved = (business) => {}, onClose }`. Loads `/api/payment-terms/` on open. Create = `check-name` → POST contact → POST business (the existing three-step order), with both duplicate sub-states.

- [ ] **Step 1: Write the failing test**

`frontend/tests/components/contacts/BusinessFormModal.test.js` — same harness as Task 2's test (`push`, `api` mocks). Cases:
```js
async function fillCreate(getByLabelText) {
  await fireEvent.input(getByLabelText(/Business Name/), { target: { value: 'Acme' } });
  await fireEvent.input(getByLabelText('First Name *'), { target: { value: 'Ann' } });
  await fireEvent.input(getByLabelText('Last Name *'), { target: { value: 'Lee' } });
  await fireEvent.input(getByLabelText('Email *'), { target: { value: 'ann@acme.test' } });
  await fireEvent.input(getByLabelText('Mobile *'), { target: { value: '555' } });
}

it('loads payment terms on open and offers them', async () => {
  api.get.mockImplementation((url) => url.startsWith('/api/payment-terms/')
    ? Promise.resolve([{ id: 1, name: 'Net 30' }]) : Promise.resolve({ results: [] }));
  const { findByRole } = render(BusinessFormModal, { props: { open: true } });
  expect(await findByRole('option', { name: 'Net 30' })).toBeInTheDocument();
});

it('create: check-name → contact → business, then navigates', async () => {
  api.get.mockImplementation((url) => url.includes('check-name') ? Promise.resolve({ exists: false }) : Promise.resolve([]));
  api.post.mockImplementation((url) => url === '/api/contacts/' ? Promise.resolve({ contact_id: 7 }) : Promise.resolve({ business_id: 11 }));
  const onClose = vi.fn();
  const { getByLabelText, getByRole, findByLabelText } = render(BusinessFormModal, { props: { open: true, onClose } });
  await findByLabelText(/Business Name/);
  await fillCreate(getByLabelText);
  await fireEvent.click(getByRole('button', { name: 'Create' }));
  await waitFor(() => expect(push).toHaveBeenCalledWith('/businesses/11'));
  expect(api.post).toHaveBeenCalledWith('/api/businesses/', expect.objectContaining({ default_contact_id: 7 }));
  expect(onClose).toHaveBeenCalled();
});

it('check-name hit shows the business notice as a sub-state (nothing created)', async () => {
  api.get.mockImplementation((url) => url.includes('check-name') ? Promise.resolve({ exists: true, business: { business_id: 2, business_name: 'Acme' } }) : Promise.resolve([]));
  const { getByLabelText, getByRole, findByText, findByLabelText } = render(BusinessFormModal, { props: { open: true } });
  await findByLabelText(/Business Name/);
  await fillCreate(getByLabelText);
  await fireEvent.click(getByRole('button', { name: 'Create' }));
  expect(await findByText('This business may already exist')).toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
  await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
  expect(getByLabelText(/Business Name/).value).toBe('Acme');
});

it('duplicate contact email from the contact POST shows the contact notice', async () => {
  api.get.mockImplementation((url) => url.includes('check-name') ? Promise.resolve({ exists: false }) : Promise.resolve([]));
  api.post.mockRejectedValue({ status: 409, data: { code: 'duplicate_email', existing_contact: { contact_id: 3, name: 'Ann Lee', email: 'ann@acme.test' } } });
  const { getByLabelText, getByRole, findByText, findByLabelText } = render(BusinessFormModal, { props: { open: true } });
  await findByLabelText(/Business Name/);
  await fillCreate(getByLabelText);
  await fireEvent.click(getByRole('button', { name: 'Create' }));
  expect(await findByText('This contact may already exist')).toBeInTheDocument();
});

it('edit: patches and calls onSaved, no navigation', async () => {
  api.get.mockResolvedValue([]);
  api.patch.mockResolvedValue({ business_id: 2, business_name: 'Acme 2' });
  const onSaved = vi.fn();
  const { getByLabelText, getByRole, findByLabelText } = render(BusinessFormModal, {
    props: { open: true, business: { business_id: 2, business_name: 'Acme', default_contact: null }, onSaved },
  });
  await findByLabelText(/Business Name/);
  await fireEvent.input(getByLabelText(/Business Name/), { target: { value: 'Acme 2' } });
  await fireEvent.click(getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/api/businesses/2/', expect.objectContaining({ business_name: 'Acme 2' })));
  expect(onSaved).toHaveBeenCalled();
  expect(push).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd frontend && npx vitest run tests/components/contacts/BusinessFormModal.test.js` → FAIL (module not found).

- [ ] **Step 3: Write `BusinessFormModal.svelte`**

```svelte
<script>
  // Business create/edit in Modal (replaces routes/contacts/BusinessFormPage,
  // 2026-10-10). Create is the three-step dance from
  // contacts-and-businesses.md "Circular-dependency creation order":
  // check-name → create Contact → create Business with default_contact_id,
  // so a name collision never orphans a contact. Both duplicate prompts are
  // in-modal sub-states (form hidden, not unmounted).
  import { push } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import LoadState from '../LoadState.svelte';
  import BusinessForm from './BusinessForm.svelte';
  import DuplicateContactNotice from './DuplicateContactNotice.svelte';
  import DuplicateBusinessNotice from './DuplicateBusinessNotice.svelte';

  let {
    open = false,
    business = null,       // null → create; detail object → edit
    onSaved = () => {},    // edit only
    onClose = () => {},
  } = $props();

  const isEdit = $derived(!!business);

  let paymentTerms = $state([]);
  let loading = $state(true);
  let formError = $state('');
  let fieldErrs = $state({});
  let duplicateContact = $state(null);
  let duplicateBusiness = $state(null);

  async function load() {
    loading = true;
    try {
      paymentTerms = await api.get('/api/payment-terms/');
    } catch (e) {
      showError(errorMessage(e, 'Could not load payment terms.'));
      paymentTerms = [];
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (open) {
      formError = ''; fieldErrs = {}; duplicateContact = null; duplicateBusiness = null;
      load();
    }
  });

  async function handleSubmit(data) {
    formError = ''; fieldErrs = {}; duplicateContact = null; duplicateBusiness = null;
    try {
      if (isEdit) {
        const updated = await api.patch(`/api/businesses/${business.business_id}/`, data);
        onSaved(updated);
        return;
      }
      const nameCheck = await api.get(`/api/businesses/check-name/?name=${encodeURIComponent(data.business_name)}`);
      if (nameCheck.exists) { duplicateBusiness = nameCheck.business; return; }
      const contactData = data._contact;
      delete data._contact;
      const contact = await api.post('/api/contacts/', contactData);
      data.default_contact_id = contact.contact_id;
      const created = await api.post('/api/businesses/', data);
      onClose();
      push(`/businesses/${created.business_id}`);
    } catch (e) {
      if (!isEdit && e.status === 409 && e.data?.code === 'duplicate_email') {
        duplicateContact = e.data.existing_contact; return;
      }
      if (!isEdit && e.status === 409 && e.data?.code === 'duplicate_business_name') {
        duplicateBusiness = e.data.existing_business; return;
      }
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { formError = t.message; fieldErrs = t.fields; }
    }
  }

  const noticeShowing = $derived(!!duplicateContact || !!duplicateBusiness);

  function handleCancel() {
    if (noticeShowing) { duplicateContact = null; duplicateBusiness = null; }
    else onClose();
  }

  function go(path) { onClose(); push(path); }
</script>

<!-- Enter is owned by BusinessForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={handleCancel} maxWidth="680px" label={isEdit ? 'Edit business' : 'New business'}>
  <h3 class="modal-title">{isEdit ? 'Edit Business' : 'New Business'}</h3>

  {#if duplicateContact}
    <DuplicateContactNotice contact={duplicateContact}
      onViewExisting={() => go(`/contacts/${duplicateContact.contact_id}`)}
      onBack={() => { duplicateContact = null; }} />
  {:else if duplicateBusiness}
    <DuplicateBusinessNotice business={duplicateBusiness}
      onViewExisting={() => go(`/businesses/${duplicateBusiness.business_id}`)}
      onBack={() => { duplicateBusiness = null; }} />
  {/if}

  <div hidden={noticeShowing}>
    <LoadState {loading}>
      <BusinessForm {business} {paymentTerms} errors={fieldErrs} {formError}
        onSubmit={handleSubmit} onCancel={onClose} />
    </LoadState>
  </div>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
```

- [ ] **Step 4: Hosts**

- `ContactListPage.svelte`: replace the remaining `<a href="#/businesses/new">New Business</a>` with `{#if $canManageJobs}<button type="button" onclick={() => { newBusinessOpen = true; }}>New Business</button>{/if}` and render `<BusinessFormModal open={newBusinessOpen} onClose={() => { newBusinessOpen = false; }} />`.
- `BusinessListPage.svelte:40`: same button + modal (import `canManageJobs`).
- `BusinessDetailPage.svelte:97`: `onEdit={() => { editOpen = true; }}` and `<BusinessFormModal open={editOpen} {business} onSaved={() => { editOpen = false; loadBusiness(); }} onClose={() => { editOpen = false; }} />` inside the `{#if business}` block.
- `App.svelte`: remove `BusinessFormPage` import; `'/businesses/new': wrap({ component: RedirectTo, props: { to: '/businesses' } })`, `'/businesses/:id/edit': wrap({ component: RedirectTo, props: { to: '/businesses/:id' } })`.
- Delete `BusinessFormPage.svelte`; grep for stragglers.

Add to `ContactListPage.test.js` the New Business sibling of the Task 2 test (button present for manager, opens `dialog` named 'New business').

- [ ] **Step 5: Run tests + build**

Run: `cd frontend && npx vitest run tests/components/contacts && npm run build` → PASS.

- [ ] **Step 6: E2E**

`e2e/specs/contacts/business-modal.spec.js` — mirror of Task 2's spec: `/#/contacts` → button "New Business" → dialog 'New business' → fill `Business Name *`, the nested `First Name *`/`Last Name *`/`Email *`/`Mobile *` → Create → URL `#/businesses/\d+` → Edit → dialog 'Edit business' → change name → Save → stays → duplicate: new business with the same name → `This business may already exist` inside the same dialog → Go Back keeps the name → Cancel.

Update `e2e/specs/settings/payment-terms.spec.js:42-44`:
```js
// The new term is offered on the business form's assignment select (the
// form is a modal over the contacts list since 2026-10-10).
await page.goto('/#/contacts');
await page.getByRole('button', { name: 'New Business' }).click();
await expect(page.getByRole('dialog', { name: 'New business' }).locator('#terms option', { hasText: 'Net 45 EOM E2E' }))
  .toHaveCount(1);
await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
```
Run: `cd e2e && npx playwright test specs/contacts/business-modal.spec.js specs/settings/payment-terms.spec.js` → PASS.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src frontend/tests e2e/specs
git commit -m "feat(contacts): business create/edit opens in BusinessFormModal

Replaces BusinessFormPage; both duplicate prompts are in-modal sub-states.
/businesses/new and /:id/edit redirect to their host pages.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Job create → `JobCreateModal` (A3)

**Files:**
- Create: `frontend/src/components/jobs/JobCreateModal.svelte`
- Modify: `components/board/NewJobButton.svelte`, `routes/jobs/JobListPage.svelte:17`, `components/contacts/ContactDetail.svelte:142`, `components/contacts/BusinessDetail.svelte:113`, `App.svelte`
- Delete: `routes/jobs/JobFormPage.svelte`
- Test: `tests/components/jobs/JobCreateModal.test.js` (new); update `tests/components/board/NewJobButton.test.js`, `tests/components/jobs/JobListPage.test.js`, `ContactDetail.test.js`, `BusinessDetail.test.js`
- E2E: update `e2e/specs/job-creation/board-new-job.spec.js`

**Interfaces:**
- Produces `JobCreateModal` — props `{ open, defaultContactId = null, onClose }`. Loads `/api/auth/users/` on open; POST `/api/jobs/`; `onClose()` then `push('/jobs/{id}')`.

- [ ] **Step 1: Failing test** `tests/components/jobs/JobCreateModal.test.js` (mock `push`, `api.get`→users, `api.post`):
```js
it('loads users on open and lists them in the PM select', async () => {
  api.get.mockResolvedValue([{ id: 2, name: 'Bob Brown' }]);
  const { findByRole } = render(JobCreateModal, { props: { open: true } });
  expect(await findByRole('option', { name: 'Bob Brown' })).toBeInTheDocument();
});
it('seeds the contact from defaultContactId and posts it', async () => {
  api.get.mockImplementation((url) => url.startsWith('/api/auth/users/') ? Promise.resolve([]) : Promise.resolve({ results: [] }));
  api.post.mockResolvedValue({ job_id: 77 });
  const onClose = vi.fn();
  const { findByRole } = render(JobCreateModal, { props: { open: true, defaultContactId: 5, onClose } });
  await fireEvent.click(await findByRole('button', { name: 'Create' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/jobs/', expect.objectContaining({ contact: 5 })));
  expect(onClose).toHaveBeenCalled();
  expect(push).toHaveBeenCalledWith('/jobs/77');
});
it('renders field errors and stays open', async () => {
  api.get.mockResolvedValue([]);
  api.post.mockRejectedValue({ status: 400, data: { contact: ['This field is required.'] } });
  const onClose = vi.fn();
  const { findByRole, findByText } = render(JobCreateModal, { props: { open: true, onClose } });
  await fireEvent.click(await findByRole('button', { name: 'Create' }));
  expect(await findByText('This field is required.')).toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
});
```
Run → FAIL.

- [ ] **Step 2: Write `JobCreateModal.svelte`**

```svelte
<script>
  // From-scratch job creation in Modal (replaces routes/jobs/JobFormPage,
  // 2026-10-10). Opens from the board's New Job button, the jobs list, and
  // a contact/business page (which pre-selects the customer). Edit and
  // Duplicate were already JobEditModal / DuplicateJobModal — this closes
  // the gap. Lands on the new job on success.
  import { push } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import LoadState from '../LoadState.svelte';
  import JobForm from './JobForm.svelte';

  let { open = false, defaultContactId = null, onClose = () => {} } = $props();

  let users = $state([]);
  let loading = $state(true);
  let formError = $state('');
  let fieldErrs = $state({});

  async function load() {
    loading = true;
    try { users = await api.get('/api/auth/users/'); }
    catch (e) { showError(errorMessage(e, 'Could not load.')); users = []; }
    finally { loading = false; }
  }

  $effect(() => { if (open) { formError = ''; fieldErrs = {}; load(); } });

  async function handleSubmit(data) {
    formError = ''; fieldErrs = {};
    try {
      const created = await api.post('/api/jobs/', data);
      onClose();
      push(`/jobs/${created.job_id}`);
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { formError = t.message; fieldErrs = t.fields; }
    }
  }
</script>

<!-- Enter is owned by JobForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="640px" label="New job">
  <h3 class="modal-title">New Job</h3>
  <LoadState {loading}>
    <JobForm {users} {defaultContactId} errors={fieldErrs} {formError}
      onSubmit={handleSubmit} onCancel={onClose} />
  </LoadState>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
```

- [ ] **Step 3: Hosts**

`NewJobButton.svelte` — whole file:
```svelte
<script>
  // The board's New Job entry point, one per pillar header (only one pillar
  // is expanded at a time, so exactly one is on screen). Absolutely
  // positioned so it sits top-right without pushing the centered title.
  // It opens JobCreateModal in place (buttons act) — 2026-10-10, the create
  // form became a modal as RM anticipated on 2026-07-31.
  import { canManageJobs } from '../../stores/permissions.js';
  import JobCreateModal from '../jobs/JobCreateModal.svelte';
  let open = $state(false);
</script>

{#if $canManageJobs}
  <button type="button" class="new-job" onclick={() => { open = true; }}>New Job</button>
  <JobCreateModal {open} onClose={() => { open = false; }} />
{/if}

<style>
  .new-job {
    position: absolute; right: 16px; top: 12px;
    padding: 3px 9px; border: 1px solid #d1d5db; border-radius: 3px;
    background: #fff; color: #2563eb; font-size: 12px; font-family: inherit;
    white-space: nowrap; cursor: pointer;
  }
  .new-job:hover { background: #f3f4f6; }
</style>
```
Update `NewJobButton.test.js`: first test becomes
```js
it('is a button that opens the job modal', async () => {
  const { getByRole, findByRole, queryByRole } = render(NewJobButton);
  expect(queryByRole('link', { name: 'New Job' })).toBeNull();
  await fireEvent.click(getByRole('button', { name: 'New Job' }));
  expect(await findByRole('dialog', { name: 'New job' })).toBeInTheDocument();
});
```
and the second asserts `queryByRole('button', { name: 'New Job' })` is null. Add `vi.mock('@/lib/api.js', …)` with `api.get` resolving `[]` and `vi.mock('svelte-spa-router', () => ({ push: vi.fn() }))`.

`JobListPage.svelte:17`: `{#if $canManageJobs}<button type="button" onclick={() => { newOpen = true; }}>New Job</button>{/if}` + `<JobCreateModal open={newOpen} onClose={() => { newOpen = false; }} />`; import `canManageJobs` and the modal. Update `JobListPage.test.js` if it asserts the link.

`ContactDetail.svelte:142`: `— <button type="button" class="link-btn" onclick={() => { newJobOpen = true; }}>New Job</button>` (keep/add the `$canManageJobs` guard) + `<JobCreateModal open={newJobOpen} defaultContactId={contact.contact_id} onClose={() => { newJobOpen = false; }} />`.
`BusinessDetail.svelte:113`: same with `defaultContactId={business.default_contact.contact_id}` inside the existing `{#if business.default_contact}` guard.
Add one test each: clicking New Job renders `dialog` named 'New job'.

`App.svelte`: remove `JobFormPage` import; `'/jobs/new': wrap({ component: RedirectTo, props: { to: '/jobs/board' } })`. Delete `JobFormPage.svelte`; grep.

- [ ] **Step 4: Run** `cd frontend && npx vitest run tests/components/jobs tests/components/board tests/components/contacts && npm run build` → PASS.

- [ ] **Step 5: E2E** — edit `board-new-job.spec.js`:
```js
// header comment: "RM 2026-07-31: the form itself becomes a Modal later" → "The form is JobCreateModal (2026-10-10)."
await page.getByRole('button', { name: 'New Job' }).click();
const dialog = page.getByRole('dialog', { name: 'New job' });
await expect(dialog.getByRole('heading', { name: 'New Job' })).toBeVisible();
await dialog.getByPlaceholder('Search contacts…').fill(contact.last_name);
await dialog.getByRole('listbox').getByRole('option').first().click();
await dialog.getByLabel('Name', { exact: true }).fill(jobName);
await dialog.getByRole('button', { name: 'Create' }).click();
// …URL + heading assertions unchanged…
// worker test: getByRole('button', { name: 'New Job' }) toHaveCount(0)
```
Run: `cd e2e && npx playwright test specs/job-creation/board-new-job.spec.js` → PASS.

- [ ] **Step 6: Commit** — `feat(jobs): New Job opens JobCreateModal from the board, list, contact and business pages`.

---

### Task 5: User create → `UserCreateModal` (A5)

**Files:**
- Create: `frontend/src/components/users/UserCreateModal.svelte`
- Modify: `routes/users/UserListPage.svelte:67`, `App.svelte`
- Delete: `routes/users/UserCreatePage.svelte`
- Test: `tests/components/users/UserCreateModal.test.js` (new), update `UserListPage.workSessions.test.js` only if it asserts the link
- E2E: `e2e/specs/users/create-user-modal.spec.js` (new; `configtime` persona has `can_manage_config`)

- [ ] **Step 1: Failing test** — render open, fill the six labelled fields (`Username *`, `Email *`, `First name *`, `Last name *`, `Password *`, `Confirm password *`), click "Create user" → `api.post('/api/users/', {...})`, `onClose` called, `push('/users/<id>')`; a 400 with `{ username: ['Taken.'] }` renders "Taken." and stays open.

- [ ] **Step 2: Write `UserCreateModal.svelte`** — the `<form>` from `UserCreatePage` verbatim (same ids/labels/`fieldErrors` rendering), wrapped:
```svelte
<Modal {open} onCancel={onClose} maxWidth="520px" label="New user">
  <h3 class="modal-title">New user</h3>
  <form onsubmit={handleSubmit}> …fields… 
    <p>
      <button type="submit" disabled={saving}>{saving ? 'Creating...' : 'Create user'}</button>
      <button type="button" onclick={onClose} disabled={saving}>Cancel</button>
    </p>
  </form>
</Modal>
```
with `$effect(() => { if (open) { form = { username:'', email:'', first_name:'', last_name:'', password:'', password_confirm:'' }; errors = {}; } })` and `handleSubmit` doing `const created = await api.post('/api/users/', form); onClose(); push(`/users/${created.id}`)`. Add `name="username" autocomplete="username"` on the username input (so the browser pairs it with the `new-password` fields when offering to save — see Task 16's rationale).

- [ ] **Step 3: Host** — `UserListPage.svelte:67` → `<button type="button" onclick={() => { newOpen = true; }}>New user</button>` + `<UserCreateModal open={newOpen} onClose={() => { newOpen = false; }} />`. `App.svelte`: `'/users/new': wrap({ component: RedirectTo, props: { to: '/users' } })`, drop the import, delete the page.

- [ ] **Step 4: Run** `cd frontend && npx vitest run tests/components/users && npm run build` → PASS.

- [ ] **Step 5: E2E** `e2e/specs/users/create-user-modal.spec.js` (`personas.configtime`): `/#/users` → button "New user" → dialog 'New user' → fill all six (`username: e2e-${stamp}`, password `e2e_password_1`) → "Create user" → URL `#/users/\d+` → heading `User: e2e-${stamp}`. Run it → PASS.

- [ ] **Step 6: Commit** — `feat(users): New user opens UserCreateModal over the users list`.

---

### Task 6: Email → `EmailCreateJobModal` + `EmailLinkModal` (A6, A8)

**Files:**
- Create: `frontend/src/components/email/EmailCreateJobModal.svelte`, `frontend/src/components/email/EmailLinkModal.svelte`
- Modify: `components/email/EmailActionPanel.svelte` (links → buttons via `onAction`), `routes/email/EmailDetailPage.svelte` (hosts), `App.svelte`
- Delete: `routes/email/EmailCreateJobPage.svelte`, `routes/email/EmailAssociatePage.svelte`, `routes/email/EmailAssociatePOPage.svelte`
- Test: `tests/components/email/EmailCreateJobModal.test.js`, `tests/components/email/EmailLinkModal.test.js` (new); update `EmailActionPanel.test.js`; delete `EmailAssociatePage.test.js` / `EmailAssociatePOPage.test.js` after porting their one regression ("search input present on mount") into `EmailLinkModal.test.js`
- E2E: update `e2e/specs/email/inbox-and-po-link.spec.js`; add `e2e/specs/email/create-job-modal.spec.js`

**Interfaces:**
- `EmailCreateJobModal` — props `{ emailRecordId, open, onClose }`. Loads `emailApi.senderInfo(id)` on open; `SenderResolutionForm` + Job Name/Description; both duplicate sub-states; success → `onClose(); push('/jobs/{id}')`.
- `EmailLinkModal` — props `{ emailRecordId, kind: 'job' | 'po', open, onLinked, onClose }`. Renders `JobPicker` or `PurchaseOrderPicker`; submit → `emailApi.linkToJob` / `linkToPo`; `onLinked()`.
- `EmailActionPanel` gains `onAction = (name) => {}` with names `'create-job' | 'link-job' | 'link-po'`; the `create-po` link is unchanged (parked).

- [ ] **Step 1: Failing tests**

`EmailCreateJobModal.test.js` (mock `@/lib/email.js` `emailApi.senderInfo`, `emailApi.createJob`, `resolveSenderToContact`; mock `push`):
```js
it('loads sender info on open and prefills the job name from the subject', async () => {
  emailApi.senderInfo.mockResolvedValue({ subject: 'Quote please', suggested_body: 'body', matching_contacts: [{ id: 4, name: 'A' }], matching_businesses: [] });
  const { findByLabelText } = render(EmailCreateJobModal, { props: { emailRecordId: 1, open: true } });
  expect((await findByLabelText(/Job Name/)).value).toBe('Quote please');
});
it('creates the job and navigates', async () => {
  emailApi.senderInfo.mockResolvedValue({ subject: 'Q', suggested_body: '', matching_contacts: [{ id: 4, name: 'A' }], matching_businesses: [] });
  resolveSenderToContact.mockResolvedValue({ contactId: 4 });
  emailApi.createJob.mockResolvedValue({ job_id: 31 });
  const onClose = vi.fn();
  const { findByRole } = render(EmailCreateJobModal, { props: { emailRecordId: 1, open: true, onClose } });
  await fireEvent.click(await findByRole('button', { name: 'Create Job' }));
  await waitFor(() => expect(emailApi.createJob).toHaveBeenCalledWith(1, expect.objectContaining({ contact: 4, name: 'Q' })));
  expect(onClose).toHaveBeenCalled();
  expect(push).toHaveBeenCalledWith('/jobs/31');
});
it('duplicate contact → notice sub-state; Go Back returns to the form', async () => {
  emailApi.senderInfo.mockResolvedValue({ subject: 'Q', suggested_body: '', matching_contacts: [], matching_businesses: [], sender_name: 'Ann Lee', sender_email: 'a@b.c' });
  resolveSenderToContact.mockRejectedValue({ status: 409, data: { code: 'duplicate_email', existing_contact: { contact_id: 9, name: 'Ann Lee', email: 'a@b.c' } } });
  const { findByRole, findByText, getByRole, getByLabelText } = render(EmailCreateJobModal, { props: { emailRecordId: 1, open: true } });
  await fireEvent.click(await findByRole('button', { name: 'Create Job' }));
  expect(await findByText('This contact may already exist')).toBeInTheDocument();
  await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
  expect(getByLabelText(/Job Name/).value).toBe('Q');
});
```
`EmailLinkModal.test.js` (mock `emailApi.get`? not needed — the modal does not load the email; mock `api.get` for the pickers and `emailApi.linkToJob`/`linkToPo`):
```js
it('renders the job search input on mount (regression: value must start null)', async () => {
  const { findByPlaceholderText } = render(EmailLinkModal, { props: { emailRecordId: 1, kind: 'job', open: true } });
  expect(await findByPlaceholderText('Search jobs…')).toBeInTheDocument();
});
it('renders the PO search input for kind=po', async () => { /* placeholder 'Search purchase order…' */ });
it('submit without a selection shows a message and does not call the API', async () => { /* 'Please select a job.' */ });
```

- [ ] **Step 2: Write `EmailCreateJobModal.svelte`** — port `EmailCreateJobPage`'s script (load/handleSubmit) with: `$effect(() => { if (open) { submitError = null; duplicateContact = null; duplicateBusiness = null; load(); } })`, success `onClose(); push(...)`, and template:
```svelte
<Modal {open} onCancel={handleCancel} maxWidth="720px" label="Create job from email">
  <h3 class="modal-title">Create Job from Email</h3>
  {#if duplicateContact}
    <DuplicateContactNotice contact={duplicateContact} onViewExisting={() => go(`/contacts/${duplicateContact.contact_id}`)} onBack={() => { duplicateContact = null; }} />
  {:else if duplicateBusiness}
    <DuplicateBusinessNotice business={duplicateBusiness} onViewExisting={() => go(`/businesses/${duplicateBusiness.business_id}`)} onBack={() => { duplicateBusiness = null; }} />
  {/if}
  <div hidden={!!duplicateContact || !!duplicateBusiness}>
    <LoadState {loading} error={loadError}>
    {#if senderInfo}
      <form onsubmit={handleSubmit}>
        <SenderResolutionForm {senderInfo} bind:state={resolutionState} />
        <h3>Job</h3>
        <p><label for="job_name"><strong>Job Name *</strong> (max 50 chars)</label><br>
          <input type="text" id="job_name" bind:value={jobName} maxlength="50" required></p>
        <p><label for="job_description"><strong>Description</strong></label><br>
          <textarea id="job_description" bind:value={jobDescription} rows="8" cols="60"></textarea></p>
        <p>
          <button type="submit" disabled={submitting}>{submitting ? 'Creating…' : 'Create Job'}</button>
          <button type="button" onclick={onClose} disabled={submitting}>Cancel</button>
        </p>
        <FormMessage error={submitError || ''} />
      </form>
    {/if}
    </LoadState>
  </div>
</Modal>
```
`handleCancel` backs out of a notice first, as in Task 2. Replace the page's `submitError = err.message` with `triageError` → `FormMessage` (`submitError = t.message`, `showError(t.overlay)` when overlay).

- [ ] **Step 3: Write `EmailLinkModal.svelte`**
```svelte
<script>
  // Link an email to an existing Job or Purchase Order (replaces
  // EmailAssociatePage / EmailAssociatePOPage, 2026-10-10). The email stays
  // visible behind the modal, which is the whole point of linking.
  import { emailApi } from '../../lib/email.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import FormMessage from '../FormMessage.svelte';
  import JobPicker from '../JobPicker.svelte';
  import PurchaseOrderPicker from '../PurchaseOrderPicker.svelte';

  let { emailRecordId, kind = 'job', open = false, onLinked = () => {}, onClose = () => {} } = $props();

  // null, never '' — SearchPicker treats '' as a real value and tries to
  // resolve a label for it (the old EmailAssociatePage regression).
  let selectedId = $state(null);
  let submitting = $state(false);
  let submitError = $state('');

  $effect(() => { if (open) { selectedId = null; submitting = false; submitError = ''; } });

  const isJob = $derived(kind === 'job');

  async function handleSubmit(e) {
    e.preventDefault();
    if (!selectedId) { submitError = isJob ? 'Please select a job.' : 'Please select a purchase order.'; return; }
    submitting = true; submitError = '';
    try {
      if (isJob) await emailApi.linkToJob(emailRecordId, selectedId);
      else await emailApi.linkToPo(emailRecordId, selectedId);
      onLinked();
    } catch (err) {
      const t = triageError(err);
      if (t.overlay) showError(t.overlay); else submitError = t.message;
    } finally { submitting = false; }
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="560px" label={isJob ? 'Link to job' : 'Link to purchase order'}>
  <h3 class="modal-title">{isJob ? 'Link to existing job' : 'Link to existing purchase order'}</h3>
  <form onsubmit={handleSubmit}>
    <p>
      <label><strong>{isJob ? 'Job' : 'Purchase Order'} *</strong></label><br>
      {#if isJob}<JobPicker bind:value={selectedId} />{:else}<PurchaseOrderPicker bind:value={selectedId} />{/if}
    </p>
    <p>
      <button type="submit" disabled={submitting}>{submitting ? 'Linking…' : (isJob ? 'Link to job' : 'Link to purchase order')}</button>
      <button type="button" onclick={onClose} disabled={submitting}>Cancel</button>
    </p>
    <FormMessage error={submitError} />
  </form>
</Modal>
```

- [ ] **Step 4: Panel + page**

`EmailActionPanel.svelte`: add `onAction = () => {}` to props. Replace the Job section's two links with
```svelte
<p><button type="button" class="action-button" onclick={() => onAction('create-job')}>Create new</button></p>
<p><button type="button" class="action-button" onclick={() => onAction('link-job')}>Link existing</button></p>
```
and the PO section's "Link existing" link with `<button type="button" class="action-button" onclick={() => onAction('link-po')}>Link existing</button>` (its "Create new" `<a … /create-po>` stays). `.action-button` already styles both tags.

`EmailDetailPage.svelte`: add `let actionModal = $state(null);` (`'create-job' | 'link-job' | 'link-po' | null`), pass `onAction={(name) => (actionModal = name)}` to the panel, and after the layout:
```svelte
<EmailCreateJobModal emailRecordId={email.email_record_id} open={actionModal === 'create-job'} onClose={() => (actionModal = null)} />
<EmailLinkModal emailRecordId={email.email_record_id} kind="job" open={actionModal === 'link-job'}
  onLinked={() => { actionModal = null; load(); }} onClose={() => (actionModal = null)} />
<EmailLinkModal emailRecordId={email.email_record_id} kind="po" open={actionModal === 'link-po'}
  onLinked={() => { actionModal = null; load(); }} onClose={() => (actionModal = null)} />
```
`App.svelte`: `'/email/:id/create-job'`, `'/email/:id/associate'`, `'/email/:id/associate-po'` → `wrap({ component: RedirectTo, props: { to: '/email/:id' } })`; drop the three imports; delete the three pages and the two old tests. Update `EmailActionPanel.test.js` so Job "Create new"/"Link existing" are buttons calling `onAction`.

- [ ] **Step 5: Run** `cd frontend && npx vitest run tests/components/email && npm run build` → PASS.

- [ ] **Step 6: E2E**

`inbox-and-po-link.spec.js` — replace the link clicks and the associate page with:
```js
const poSection = panel.locator('section', { has: page.getByRole('heading', { name: 'Purchase Order' }) });
await poSection.getByRole('button', { name: 'Link existing' }).click();
const dialog = page.getByRole('dialog', { name: 'Link to purchase order' });
await dialog.getByPlaceholder('Search purchase order…').fill('PO0001');
await dialog.getByText(/PO0001 — Moore Newton Hardwoods/).click();
await dialog.getByRole('button', { name: 'Link to purchase order' }).click();
await expect(page.getByRole('dialog')).toHaveCount(0);
// …linked assertions unchanged; the final re-check becomes:
await expect(poSection.getByRole('button', { name: 'Link existing' })).toBeVisible();
```
New `e2e/specs/email/create-job-modal.spec.js` (`finjobs`): via `apiAs`, `GET /api/emails/?page_size=50` and pick the first record with `job == null` (skip the test if none); open `/#/email/{id}`; Job section → "Create new" → dialog 'Create job from email' → `getByRole('heading', { name: 'Sender' })` visible → set `Job Name *` to `${stamp} from email` → "Create Job" → URL `#/jobs/\d+` and heading matching the name. Then via API `POST /api/emails/{id}/unlink-from-job/` (the `emailApi.unlinkFromJob` route) so reruns start from seed state.
Run: `cd e2e && npx playwright test specs/email` → PASS.

- [ ] **Step 7: Commit** — `feat(email): create-job and link-existing open modals over the email detail page`.

---

### Task 7: Document send → `DocumentSendModal` (A9: estimate, change order, invoice)

**Files:**
- Create: `frontend/src/components/email/DocumentSendModal.svelte`
- Modify: `components/email/DocumentSendForm.svelte` (optional `onCancel` → Cancel button), `components/estimates/EstimatePanel.svelte`, `components/changeorders/ChangeOrderPanel.svelte`, `components/invoices/InvoicePanel.svelte`, `App.svelte`
- Delete: `routes/estimates/EstimateSendPage.svelte`, `routes/change-orders/ChangeOrderSendPage.svelte`, `routes/invoices/InvoiceSendPage.svelte`, `tests/routes/invoices/InvoiceSendPage.test.js` (ported)
- Keep untouched: `routes/purchaseorders/PurchaseOrderSendPage.svelte` (parked).
- Test: `tests/components/email/DocumentSendModal.test.js` (new); update `DocumentSendForm.test.js`, `EstimatePanel.test.js` (§"Send Email deliverables gate"), `ChangeOrderPanel.test.js` (send tests), `InvoicePanel.test.js` (send link tests)
- E2E: update `estimate-lifecycle/send-deliverables-gate.spec.js`, `change-orders/deliverables-gate.spec.js`, `change-orders/send-gate.spec.js`, `invoice-skeleton/seeded-invoice.spec.js`, `comment-lines/invoice-comment.spec.js`

**Interfaces:**
- `DocumentSendModal` — props `{ open, label, title, defaultsUrl, sendUrl, submitLabel = 'Send Email', beforeSubmit = async () => true, onSent, onClose }`. On open: `api.get(defaultsUrl)` → `sendDefaults`. On form submit (after `DocumentSendForm`'s own `confirm()`): `if (!(await beforeSubmit())) return;` then `api.postMultipart(sendUrl, fd)` with the same FormData the pages built; `onSent()` on success; errors → `FormMessage` via `triageError`.
- `DocumentSendForm` gains `onCancel = null`; when set, renders `<button type="button" onclick={onCancel}>Cancel</button>` beside the submit.
- The doc-ref summaries the pages rendered under the form are dropped (the document is behind the modal — RM 2026-10-10).

- [ ] **Step 1: Failing tests** `tests/components/email/DocumentSendModal.test.js` (mock `api.get`, `api.postMultipart`; spy `window.confirm` → true):
```js
const PROPS = { open: true, label: 'Send estimate', title: 'Send Estimate', defaultsUrl: '/api/estimates/7/send-defaults/', sendUrl: '/api/estimates/7/send/', submitLabel: 'Send Email' };
it('loads defaults on open and prefills To', async () => {
  api.get.mockResolvedValue({ to: 'cust@example.com', cc: '', bcc: '', subject: 'S', body: 'B', attachments_preview: [] });
  const { findByDisplayValue } = render(DocumentSendModal, { props: PROPS });
  expect(await findByDisplayValue('cust@example.com')).toBeInTheDocument();
});
it('posts multipart to sendUrl and calls onSent', async () => {
  api.get.mockResolvedValue({ to: 'c@x.y', attachments_preview: [] });
  api.postMultipart.mockResolvedValue({});
  const onSent = vi.fn();
  const { findByRole } = render(DocumentSendModal, { props: { ...PROPS, onSent } });
  await fireEvent.click(await findByRole('button', { name: 'Send Email' }));
  await waitFor(() => expect(api.postMultipart).toHaveBeenCalledWith('/api/estimates/7/send/', expect.any(FormData)));
  expect(onSent).toHaveBeenCalled();
});
it('beforeSubmit false aborts without posting and keeps the modal open', async () => {
  api.get.mockResolvedValue({ to: 'c@x.y', attachments_preview: [] });
  const { findByRole, getByDisplayValue } = render(DocumentSendModal, { props: { ...PROPS, beforeSubmit: async () => false } });
  await fireEvent.click(await findByRole('button', { name: 'Send Email' }));
  await waitFor(() => expect(window.confirm).toHaveBeenCalled());
  expect(api.postMultipart).not.toHaveBeenCalled();
  expect(getByDisplayValue('c@x.y')).toBeInTheDocument();
});
it('renders the server refusal as a form message and stays open', async () => {
  api.get.mockResolvedValue({ to: 'c@x.y', attachments_preview: [] });
  api.postMultipart.mockRejectedValue({ status: 400, data: { detail: 'Cannot send an empty change order.' }, message: 'Cannot send an empty change order.' });
  const onClose = vi.fn();
  const { findByRole, findByText } = render(DocumentSendModal, { props: { ...PROPS, onClose } });
  await fireEvent.click(await findByRole('button', { name: 'Send Email' }));
  expect(await findByText('Cannot send an empty change order.')).toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
});
it('Cancel closes', async () => { /* click 'Cancel' → onClose called */ });
```
Port from `InvoiceSendPage.test.js` into `InvoicePanel.test.js` (Task step 4 below): "declining the deposit-credit confirm does not post".

- [ ] **Step 2: Write `DocumentSendModal.svelte`**
```svelte
<script>
  // The send step for estimates / change orders / invoices, in Modal over
  // the document panel (replaces the three *SendPage routes, 2026-10-10 —
  // the standing "send buttons navigate" exception in CLAUDE.md is now
  // moot). The panel passes URLs; this owns the defaults fetch, the
  // multipart POST, and error rendering. `beforeSubmit` is the invoice
  // panel's hook for its unapplied-deposit-credit confirm — it runs AFTER
  // DocumentSendForm's own "Send this email to …?" confirm.
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import LoadState from '../LoadState.svelte';
  import DocumentSendForm from './DocumentSendForm.svelte';

  let {
    open = false,
    label = 'Send',
    title = 'Send',
    defaultsUrl,
    sendUrl,
    submitLabel = 'Send Email',
    beforeSubmit = async () => true,
    onSent = () => {},
    onClose = () => {},
  } = $props();

  let sendDefaults = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true; loadError = null; sendDefaults = null;
    try { sendDefaults = await api.get(defaultsUrl); }
    catch (e) { loadError = errorMessage(e, 'Could not load the email defaults.'); }
    finally { loading = false; }
  }

  $effect(() => { if (open && defaultsUrl) { submitError = null; submitting = false; load(); } });

  async function handleSubmit(payload) {
    if (!(await beforeSubmit())) return;
    submitting = true; submitError = null;
    try {
      const fd = new FormData();
      fd.append('to', payload.to);
      fd.append('cc', payload.cc);
      fd.append('bcc', payload.bcc);
      fd.append('subject', payload.subject);
      fd.append('body', payload.body);
      for (const file of payload.extraFiles) fd.append('attachments', file);
      await api.postMultipart(sendUrl, fd);
      onSent();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay); else submitError = t.message;
    } finally { submitting = false; }
  }
</script>

<!-- Enter is owned by DocumentSendForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="780px" {label}>
  <h3 class="modal-title">{title}</h3>
  <LoadState {loading} error={loadError}>
    {#if sendDefaults}
      <DocumentSendForm {sendDefaults} {submitLabel} {submitting} {submitError}
        onSubmit={handleSubmit} onCancel={onClose} />
    {/if}
  </LoadState>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
```
`DocumentSendForm.svelte`: add `onCancel = null` to props and change the submit paragraph to
```svelte
<p>
  <button type="submit" disabled={submitting || !to.trim()}>{submitting ? 'Sending…' : submitLabel}</button>
  {#if onCancel}<button type="button" onclick={onCancel} disabled={submitting}>Cancel</button>{/if}
</p>
```
Add a `DocumentSendForm.test.js` case: "renders Cancel only when onCancel is given".

- [ ] **Step 3: Hosts**

`EstimatePanel.svelte`: replace `goToSend()` body with `sendOpen = true;` (add `let sendOpen = $state(false);`, remove the `window.location.hash` line and the "slated to become a modal" comment → "the email step is DocumentSendModal (2026-10-10)"). After the `DeliverablesEditModal` block:
```svelte
{#if estimate}
  <DocumentSendModal open={sendOpen} label="Send estimate" title="Send Estimate"
    defaultsUrl={`/api/estimates/${estimate.estimate_id}/send-defaults/`}
    sendUrl={`/api/estimates/${estimate.estimate_id}/send/`}
    submitLabel="Send Email"
    onSent={async () => { sendOpen = false; await loadEstimate({ silent: true }); onJobChange(); }}
    onClose={() => { sendOpen = false; }} />
{/if}
```
`ChangeOrderPanel.svelte`: same (`loadCO({ silent: true })`, label "Send change order", title "Send change order to customer", URLs under `/api/change-orders/${co.change_order_id}/`).
`InvoicePanel.svelte:381-388`: the `<a class="action-link" href="#/invoices/…/send">` becomes `<button type="button" class="action-link" onclick={() => { sendOpen = true; }}>{invoice.qbo_id ? 'Resend Invoice' : 'Send Invoice'}</button>`, and:
```svelte
{#if invoice}
  <DocumentSendModal open={sendOpen} label="Send invoice" title="Send Invoice"
    defaultsUrl={`/api/invoices/${invoice.invoice_id}/send-defaults/`}
    sendUrl={`/api/invoices/${invoice.invoice_id}/send/`}
    submitLabel="Send Invoice"
    beforeSubmit={confirmDepositCredits}
    onSent={async () => { sendOpen = false; await loadInvoice({ silent: true }); await loadInvoices(); onJobChange(); }}
    onClose={() => { sendOpen = false; }} />
{/if}
```
with, in the script (next to the existing `unappliedCredits` derived):
```js
// Soft guard, not a hard block (invoicing-and-expenses.md "Part 2 — send-time
// confirm"): refresh the job's invoices, then ask. Runs after
// DocumentSendForm's own recipient confirm.
async function confirmDepositCredits() {
  await loadInvoices();
  if (unappliedCredits.length === 0) return true;
  return confirm("There's an unapplied deposit credit on this job — send anyway?");
}
```
`App.svelte`: `'/estimates/:id/send'` → `wrap({ component: RedirectTo, props: { to: '/estimates/:id' } })`, `'/change-orders/:id/send'` → `to: '/change-orders/:id'`, `'/invoices/:id/send'` → `to: '/invoices/:id'`; drop the three imports; delete the three pages.

- [ ] **Step 4: Update the panel tests**

`EstimatePanel.test.js` "Send Email deliverables gate": every `expect(window.location.hash).toBe('#/estimates/7/send')` becomes `expect(await findByRole('dialog', { name: 'Send estimate' })).toBeInTheDocument()`; every `.toBe('')` after a gate-open becomes `expect(queryByRole('dialog', { name: 'Send estimate' })).toBeNull()`. Add `api.get` handling for `/api/estimates/7/send-defaults/` → `{ to: 'c@x.y', attachments_preview: [] }`. Same shape for `ChangeOrderPanel.test.js` (`'Send change order'`). `InvoicePanel.test.js`: `findByRole('link', { name: /send invoice/i })` → `findByRole('button', …)`; `queryByRole('link', …)).not.toBeInTheDocument()` cases become `expect(await findByRole('button', { name: /send invoice/i })).toBeDisabled()`; add
```js
it('declining the deposit-credit confirm leaves the send modal open and does not post', async () => {
  // invoices list mock includes an unapplied deposit credit (reuse the fixture InvoiceSendPage.test.js used)
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(true).mockReturnValueOnce(false);
  await fireEvent.click(await findByRole('button', { name: /send invoice/i }));
  const dialog = await findByRole('dialog', { name: 'Send invoice' });
  await fireEvent.click(within(dialog).getByRole('button', { name: 'Send Invoice' }));
  await waitFor(() => expect(confirmSpy).toHaveBeenCalledTimes(2));
  expect(api.postMultipart).not.toHaveBeenCalled();
  expect(within(dialog).getByLabelText('To *')).toBeInTheDocument();
  confirmSpy.mockRestore();
});
```
Delete `tests/routes/invoices/InvoiceSendPage.test.js`.

- [ ] **Step 5: Run** `cd frontend && npx vitest run tests/components/email tests/components/estimates tests/components/changeorders tests/components/invoices && npm run build` → PASS.

- [ ] **Step 6: E2E updates**

- `send-deliverables-gate.spec.js`: step "…lands on the send page" → after Save: `const send = page.getByRole('dialog', { name: 'Send estimate' }); await expect(send.getByRole('heading', { name: 'Send Estimate' })).toBeVisible(); await send.getByRole('button', { name: 'Cancel' }).click();`. Step "goes straight to the send page" → `await expect(page.getByRole('dialog', { name: 'Send estimate' })).toBeVisible(); … Cancel`. Keep the `toHaveCount(0)` checks for the deliverables dialog by name: `page.getByRole('dialog', { name: 'Edit deliverables' })`.
- `change-orders/deliverables-gate.spec.js`: same substitutions with `'Send change order'`; replace `page.goBack()` with Cancel.
- `change-orders/send-gate.spec.js` §"Send page": `page.goto('/#/jobs/${job.job_id}/change-order/${co.change_order_id}')`, click "Send to customer", `const dialog = page.getByRole('dialog', { name: 'Send change order' })`, fill `dialog.getByLabel('To *')`, `page.once('dialog', d => d.accept())`, click `dialog.getByRole('button', { name: 'Send Email' })`, expect `dialog.getByText(/Cannot send an empty change order/)` visible.
- `seeded-invoice.spec.js` + `invoice-comment.spec.js`: `getByRole('link', { name: 'Send Invoice' })` → `getByRole('button', { name: 'Send Invoice' })`; heading inside `page.getByRole('dialog', { name: 'Send invoice' })`; fill/submit scoped to that dialog; the `role="alert"` assertion scoped to the dialog.
Run: `cd e2e && npx playwright test specs/estimate-lifecycle/send-deliverables-gate.spec.js specs/change-orders specs/invoice-skeleton/seeded-invoice.spec.js specs/comment-lines/invoice-comment.spec.js` → PASS.

- [ ] **Step 7: Commit** — `feat(send): estimate, change-order and invoice send open DocumentSendModal over the document panel`.

---

### Task 8: Email reply composer in a modal (B11)

**Files:**
- Modify: `components/email/EmailReplyComposer.svelte` (wrap in `<Modal>`), `routes/email/EmailDetailPage.svelte` (comment only)
- Test: update `tests/components/email/EmailReplyComposer.test.js`
- E2E: `e2e/specs/email/reply-modal.spec.js` (new)

- [ ] **Step 1: Failing test** — add to `EmailReplyComposer.test.js`:
```js
it('is a modal: renders a dialog named after the mode and Escape calls onClose', async () => {
  const onClose = vi.fn();
  const { findByRole } = render(EmailReplyComposer, { props: { emailRecordId: 1, mode: 'reply-all', onClose, onSent: vi.fn() } });
  expect(await findByRole('dialog', { name: 'Reply All' })).toBeInTheDocument();
  await fireEvent.keyDown(window, { key: 'Escape' });
  expect(onClose).toHaveBeenCalled();
});
```
Run → FAIL (no dialog).

- [ ] **Step 2: Implement** — import `Modal`; replace `<section class="composer">…</section>` with
```svelte
<!-- Enter is owned by DocumentSendForm's native <form>; the shell only wires Escape. -->
<Modal open={true} onCancel={onClose} maxWidth="780px" label={mode === 'reply-all' ? 'Reply All' : 'Reply'}>
  <div class="composer-header">
    <h3>{mode === 'reply-all' ? 'Reply All' : 'Reply'}</h3>
  </div>
  <LoadState {loading} error={loadError}>
  {#if replyDefaults}
    <DocumentSendForm … (unchanged bindings) onCancel={onClose} />
  {/if}
  </LoadState>
</Modal>
```
Drop the header's own Cancel button (the form's Cancel replaces it) and the `.composer` border/margin styles. Update the file-top comment ("Inline reply composer" → "Reply composer, in Modal over the email (2026-10-10)"). The existing test "closes via onClose" clicks `button Cancel` — still present (now from the form). `EmailDetailPage.svelte`: update the `replyMode` comment ("renders inline above the original" → "opens the composer modal over the email").

- [ ] **Step 3: Run** `cd frontend && npx vitest run tests/components/email/EmailReplyComposer.test.js tests/components/email` → PASS.

- [ ] **Step 4: E2E** `e2e/specs/email/reply-modal.spec.js` (`finjobs`): open `/#/email`, click the `Re: Estimate 08008-1` link, click "Reply" → `dialog` named 'Reply' visible with `getByLabel('To *')` non-empty → click "Reply All" (panel) → dialog name 'Reply All' → Cancel → no dialog. (Sending is live SMTP — exempt, as `send-gate.spec.js` documents.) Run → PASS.

- [ ] **Step 5: Commit** — `feat(email): reply composer opens as a modal over the email`.

---

### Task 9: Expenses → existing `ExpenseModal` (B1, B2)

**Files:**
- Modify: `routes/expenses/ExpenseListPage.svelte:115-132`, `components/home/ExpensesList.svelte:888-901`, `components/expenses/ExpenseModal.svelte` (pass-through `lockPurchasedByToSelf`)
- Test: update `tests/routes/ExpenseListPage.test.js`, `tests/components/home/ExpensesList.test.js`, `tests/components/expenses/ExpenseModal.test.js`
- E2E: run `e2e/specs/expenses/creating-expenses.spec.js` and `task-list-expense-actions.spec.js` unchanged (labels are the same)

- [ ] **Step 1: Failing tests**
`ExpenseModal.test.js`: `it('passes lockPurchasedByToSelf through to the form', …)` — render `{ open: true, lockPurchasedByToSelf: true }` and assert the "Purchased by" select is absent (the form hides it when locked — check `ExpenseForm.svelte` for the exact behaviour and assert that).
`ExpenseListPage.test.js`: `it('+ New expense opens the expense modal', …)` → click → `findByRole('dialog')` with text 'Add Expense'; `it('edit opens the modal titled Edit Expense', …)`.
`ExpensesList.test.js`: `+ New expense` → dialog with 'Add Expense'.
Run → FAIL.

- [ ] **Step 2: Implement**
`ExpenseModal.svelte`: add `lockPurchasedByToSelf = false` to props and `{lockPurchasedByToSelf}` on `<ExpenseForm>`.
`ExpenseListPage.svelte`: replace lines 115-132 with
```svelte
<p><button type="button" onclick={() => { editingExpense = null; showForm = true; }}>+ New expense</button></p>
<ExpenseModal open={showForm} expense={editingExpense} onSaved={onSaved}
  onClose={() => { showForm = false; editingExpense = null; }} />
```
(import `ExpenseModal` instead of `ExpenseForm`).
`ExpensesList.svelte`: replace the two blocks with
```svelte
<p><button type="button" onclick={() => { showForm = true; }}>+ New expense</button></p>
<ExpenseModal open={showForm} lockPurchasedByToSelf={true} onSaved={onSaved} onClose={() => { showForm = false; }} />
```

- [ ] **Step 3: Run** `cd frontend && npx vitest run tests/routes/ExpenseListPage.test.js tests/components/home tests/components/expenses` → PASS. Then `cd e2e && npx playwright test specs/expenses` → PASS (if `getByLabel('Description', { exact: false }).first()` now hits the dialog's field first, scope the helper's queries to `page.getByRole('dialog')`).

- [ ] **Step 4: Commit** — `feat(expenses): list and home expense forms use ExpenseModal`.

---

### Task 10: Catalog merge + write-off modals (B3, B4)

**Files:**
- Modify: `routes/catalog/CatalogInventoryPage.svelte:150-201`
- Test: update `tests/components/catalog/CatalogInventoryPage.test.js` (write-off / merge tests)
- E2E: `e2e/specs/inventory/merge-and-write-off.spec.js` (new)

- [ ] **Step 1: Failing tests** — in `CatalogInventoryPage.test.js` add `it('write off opens a dialog', …)` (`findByRole('dialog', { name: 'Write off' })`) and `it('Merge items opens a dialog', …)` (`'Merge items'`); keep the existing POST assertions.

- [ ] **Step 2: Implement** — replace the "Merge items" toggle button with `<button type="button" onclick={() => { showMerge = true; mergeError = ''; }}>Merge items</button>`, add `function cancelMerge() { showMerge = false; mergeKeep = ''; mergeDiscard = ''; mergeError = ''; }`, and replace the two bordered `<div>`s with:
```svelte
<Modal open={showMerge} onCancel={cancelMerge} maxWidth="640px" label="Merge items">
  <form onsubmit={(e) => { e.preventDefault(); doMerge(); }}>
    <h3>Merge items</h3>
    <p>Fold one item's stock and references into a keep item, then delete the discard. Units must match.</p>
    <p><label>Keep (survivor): <select bind:value={mergeKeep}>…unchanged options…</select></label></p>
    <p><label>Discard (folded in &amp; deleted): <select bind:value={mergeDiscard}>…</select></label></p>
    <p>
      <button type="submit">Merge</button>
      <button type="button" onclick={cancelMerge}>Cancel</button>
    </p>
    <FormMessage error={mergeError} />
  </form>
</Modal>

<Modal open={!!writeOffItem} onCancel={cancelWriteOff} maxWidth="520px" label="Write off">
  {#if writeOffItem}
  <form onsubmit={(e) => { e.preventDefault(); doWriteOff(); }}>
    <h3>Write off — {writeOffItem.code}</h3>
    <p>{writeOffItem.qty_on_hand} {writeOffItem.units} on hand. How many are wasted (damaged, mis-cut)? This can't be undone.</p>
    <p><label>Quantity to write off:
      <input type="number" step="0.01" min="0" max={writeOffItem.qty_on_hand} bind:value={writeOffQty}></label></p>
    <p><label>Reason (optional):
      <input type="text" bind:value={writeOffReason} placeholder="e.g. damaged in storage"></label></p>
    <p>
      <button type="submit">Confirm write-off</button>
      <button type="button" onclick={cancelWriteOff}>Cancel</button>
    </p>
    <FormMessage error={writeOffError} />
  </form>
  {/if}
</Modal>
```
Import `FormMessage`. Route `doMerge`/`doWriteOff` catch blocks through `triageError` → `mergeError = t.message` / `writeOffError = t.message` (overlay → `showError`).

- [ ] **Step 3: Run** `cd frontend && npx vitest run tests/components/catalog` → PASS.

- [ ] **Step 4: E2E** `e2e/specs/inventory/merge-and-write-off.spec.js` (`finjobs`): via API create two catalog items (`POST /api/inventory/` with `code: ${stamp}-A` / `-B`, same `units`, an accounting category from `/api/accounting-categories/`); `/#/catalog` → "Merge items" → `dialog` 'Merge items' → select keep A, discard B by option label → Merge → dialog closes → B's row gone. Write-off: `GET /api/inventory/?is_catalog=false&page_size=100`, pick a lot with `qty_on_hand > 0` (skip the step if none) → its row's "write off" → `dialog` 'Write off' → qty `0.01` → "Confirm write-off" → dialog closes. Run → PASS.

- [ ] **Step 5: Commit** — `feat(catalog): merge and write-off are modals`.

---

### Task 11: Service item form → modal (B8)

**Files:**
- Modify: `components/ServiceItemManager.svelte:228-285`
- Test: `tests/components/ServiceItemManager.test.js` (add dialog assertion)
- E2E: `e2e/specs/catalog/service-item-modal.spec.js` (new); re-run `estimating-structure/flat-fee.spec.js` and `add-line-and-work-authoring/estimate-gate-and-live-picker.spec.js`

- [ ] **Step 1: Failing test** — `it('Add Service Item opens a dialog', …)` → `findByRole('dialog', { name: 'New service item' })`.

- [ ] **Step 2: Implement** — import `Modal`; replace `{#if editingId !== null}<fieldset>…</fieldset>{/if}` with
```svelte
<!-- Button-driven content (no native <form>, Save is type=button like
     RateSchemeManager), so the shell takes onSave + busy. -->
<Modal open={editingId !== null} onSave={save} onCancel={cancelEdit} busy={saving} maxWidth="640px"
  label={editingId === 'new' ? 'New service item' : 'Edit service item'}>
  <h3>{editingId === 'new' ? 'New Service Item' : 'Edit Service Item'}</h3>
  …the existing field markup unchanged…
</Modal>
```
Remove the LATER.md entry "Service Item edit should be a modal" (Task 17 collects doc edits; do the LATER removal here since it is the done-when).

- [ ] **Step 3: Run** `cd frontend && npx vitest run tests/components/ServiceItemManager.test.js` → PASS.

- [ ] **Step 4: E2E** — new spec (`finjobs`): `/#/catalog/service-items` → "Add Service Item" → `dialog` 'New service item' → fill `Name *` → Save → dialog closes → row visible. Run it plus the two existing specs that click "Add Service Item" → PASS.

- [ ] **Step 5: Commit** — `feat(catalog): service item create/edit is a modal`.

---

### Task 12: Accounting category form → modal (B9)

**Files:**
- Modify: `components/settings/AccountingCategories.svelte:230-280`
- Test: `tests/components/settings/AccountingCategories.test.js` (dialog assertion)
- E2E: re-run `settings/accounting-categories.spec.js`; add a `dialog` assertion to it

- [ ] **Step 1: Failing test** — `it('Add category opens a dialog', …)` → `findByRole('dialog', { name: 'New category' })`.
- [ ] **Step 2: Implement** — wrap the `{#if adding || editing}<fieldset>` block in `<Modal open={adding || !!editing} onSave={saveForm} onCancel={cancelForm} busy={saving != null} maxWidth="560px" label={editing ? 'Edit category' : 'New category'}>` with the legend → `<h3>`. Keep button labels ("Create" / "Save Changes" / "Cancel"). Error venue: `error = e.message` → `triageError` + `FormMessage` inside the modal for save errors.
- [ ] **Step 3: Run** `cd frontend && npx vitest run tests/components/settings tests/components/qboimport` → PASS.
- [ ] **Step 4: E2E** — in `accounting-categories.spec.js` after "Add category": `const dialog = page.getByRole('dialog', { name: 'New category' }); await dialog.getByLabel('Code *')…`. Run → PASS.
- [ ] **Step 5: Commit** — `feat(settings): accounting category form is a modal`.

---

### Task 13: Reimbursement batch form → modal (B10)

**Files:**
- Modify: `components/expenses/UserReimbursementPanel.svelte:201-230`
- Test: `tests/components/expenses/UserReimbursementPanel.test.js`
- E2E: exempt — the batch form needs QBO payment accounts, which the e2e environment has no QBO connection for (the panel shows "Configure payment accounts…"). Note the exemption in the commit body.

- [ ] **Step 1: Failing test**
```js
it('Reimburse selected opens the batch modal with the count and total, and submits', async () => {
  const { findAllByRole, findByRole, findByText } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
  const checkboxes = await findAllByRole('checkbox');
  await fireEvent.click(checkboxes[1]);
  await fireEvent.click(await findByText(/Reimburse selected/));
  const dialog = await findByRole('dialog', { name: 'Create reimbursement' });
  expect(within(dialog).getByText(/1 expense/)).toBeInTheDocument();
  await fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm reimbursement' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/reimbursements/', expect.objectContaining({ purchased_by: 7 })));
});
```
- [ ] **Step 2: Implement** — replace the dashed `<div>` with
```svelte
<Modal open={showBatchForm} onCancel={() => { showBatchForm = false; }} maxWidth="520px" label="Create reimbursement">
  <form onsubmit={(e) => { e.preventDefault(); submitBatch(); }}>
    <h3>Reimburse {selectedIds.size} expense{selectedIds.size === 1 ? '' : 's'} — ${selectedTotal}</h3>
    …the four fields unchanged…
    <p>
      <button type="submit" disabled={batchSaving}>{batchSaving ? 'Saving...' : 'Confirm reimbursement'}</button>
      <button type="button" onclick={() => { showBatchForm = false; }}>Cancel</button>
    </p>
    <FormMessage error={batchError} />
  </form>
</Modal>
```
- [ ] **Step 3: Run** `cd frontend && npx vitest run tests/components/expenses/UserReimbursementPanel.test.js` → PASS.
- [ ] **Step 4: Commit** — `feat(expenses): reimbursement batch form is a modal (e2e exempt: needs QBO payment accounts)`.

---

### Task 14: Change-order deliverables inline rows → modal (C2)

**Files:**
- Modify: `components/changeorders/CODeliverablesSection.svelte`
- Test: `tests/components/changeorders/CODeliverablesSection.test.js`, `tests/components/changeorders/ChangeOrderPanel.test.js:160-200`
- E2E: update `e2e/specs/change-orders/co-room-and-diff.spec.js:116-123`

- [ ] **Step 1: Failing test** — rewrite the "adding a new deliverable" case:
```js
await fireEvent.click(getByRole('button', { name: '+ New deliverable' }));
const dialog = await findByRole('dialog', { name: 'New deliverable' });
await fireEvent.input(within(dialog).getByLabelText('Description'), { target: { value: 'Panel B' } });
await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));
await waitFor(() => expect(get(deliverablesVersion)).toBe(before + 1));
```
and add `it('Change opens the edit dialog prefilled and patches on Save', …)` (`dialog` 'Edit deliverable', `getByLabelText('Qty').value === '2'`, Save → `api.patch('/api/jobs/9/deliverables/1/', …)`).

- [ ] **Step 2: Implement** — replace the per-row edit state with one draft:
```js
// One drafting modal for both edit and new (replaces the inline
// tr.row-editing rows, 2026-10-10 — matches the estimate side's
// DeliverablesEditModal being a modal). draft.id null → new.
let draft = $state(null);   // { id, description, qty, units }
let draftError = $state('');
let draftFields = $state({});
function openEdit(liveRow) { draft = { id: liveRow.id, description: liveRow.description, qty: String(Number(liveRow.qty_ordered)), units: liveRow.units }; draftError = ''; draftFields = {}; }
function openNew() { draft = { id: null, description: '', qty: '1', units: 'ea' }; draftError = ''; draftFields = {}; }
function cancelDraft() { draft = null; draftError = ''; draftFields = {}; }
async function saveDraft() {
  draftError = ''; draftFields = {};
  if (!draft.description.trim()) { draftFields = { description: ['Description is required.'] }; return; }
  saving = true;
  const body = { description: draft.description, qty_ordered: draft.qty, units: draft.units };
  try {
    if (draft.id) await api.patch(`/api/jobs/${jobId}/deliverables/${draft.id}/`, body);
    else await api.post(`/api/jobs/${jobId}/deliverables/`, body);
    draft = null;
    notifyDeliverablesChanged();
    await onReload();
  } catch (e) {
    const t = triageError(e);
    if (t.overlay) showError(t.overlay); else { draftError = t.message; draftFields = t.fields; }
  } finally { saving = false; }
}
```
Delete `editId/editDescription/editQty/editUnits/newOpen/newDescription/newQty/newUnits/editError/editFields/newError/newFields`, `cancelEdit`, `saveEdit`, `cancelNew`, `saveNew`, `editKeydown`. In the template: remove every `{#if editId === row.live.id}<tr class="row-editing">…{:else}` branch (keep only the display rows), the `{#if newOpen}` row, and the `!newOpen` guards; "+ New deliverable" → `openNew`. Append:
```svelte
<Modal open={draft !== null} onCancel={cancelDraft} maxWidth="520px" label={draft?.id ? 'Edit deliverable' : 'New deliverable'}>
  {#if draft}
  <form onsubmit={(e) => { e.preventDefault(); if (!saving) saveDraft(); }}>
    <h3>{draft.id ? 'Edit deliverable' : 'New deliverable'}</h3>
    <p><label for="deliv-qty"><strong>Qty</strong></label><br>
      <input id="deliv-qty" type="number" step="any" min="0" bind:value={draft.qty} style="width:6em">
      <FieldError errors={draftFields} field="qty_ordered" /></p>
    <p><label for="deliv-units"><strong>Units</strong></label><br>
      <UnitsSelect id="deliv-units" bind:value={draft.units} />
      <FieldError errors={draftFields} field="units" /></p>
    <p><label for="deliv-desc"><strong>Description</strong></label><br>
      <input id="deliv-desc" type="text" bind:value={draft.description} placeholder="Description" style="width:100%;box-sizing:border-box">
      <FieldError errors={draftFields} field="description" /></p>
    <p>
      <button type="submit" disabled={saving}>{draft.id ? 'Save' : 'Add'}</button>
      <button type="button" onclick={cancelDraft} disabled={saving}>Cancel</button>
    </p>
    <FormMessage error={draftError} />
  </form>
  {/if}
</Modal>
```
(If `UnitsSelect` does not forward an `id`, wrap it in `<label>Units <UnitsSelect …/></label>` instead and query by label text.) Remove the `.row-editing`, `.edit-row-layout`, `.qty-input`, `.desc-input-inline` styles. Update `ChangeOrderPanel.test.js` cases at lines 168-186 that type into the inline row to use the dialog's labelled inputs.

- [ ] **Step 3: Run** `cd frontend && npx vitest run tests/components/changeorders` → PASS.

- [ ] **Step 4: E2E** — `co-room-and-diff.spec.js` step "+ New deliverable": 
```js
await page.getByRole('button', { name: '+ New deliverable' }).click();
const dialog = page.getByRole('dialog', { name: 'New deliverable' });
await dialog.getByLabel('Qty').fill('2');
await dialog.getByLabel('Description').fill(`${stamp} extra bracket`);
await dialog.getByRole('button', { name: 'Add', exact: true }).click();
await expect(page.locator('tr.row-added')).toContainText(`${stamp} extra bracket`);
```
Run: `cd e2e && npx playwright test specs/change-orders` → PASS.

- [ ] **Step 5: Commit** — `feat(change-orders): deliverable add/edit is a modal instead of inline rows`.

---

### Task 15: Password modals + browser autocomplete fix (F1, F2, login)

**Files:**
- Create: `frontend/src/components/users/ChangePasswordModal.svelte`, `frontend/src/components/users/ResetPasswordModal.svelte`
- Modify: `components/home/ProfilePanel.svelte` (password form → button + modal), `routes/users/UserDetailPage.svelte:286-318` (same), `routes/LoginPage.svelte` (`name`/`autocomplete`)
- Test: `tests/components/users/ChangePasswordModal.test.js`, `tests/components/users/ResetPasswordModal.test.js` (new); update `tests/components/home/ProfilePanel.test.js`, `tests/components/users/UserDetailPage.test.js`, `tests/routes/LoginPage.test.js`
- E2E: `e2e/specs/home/change-password-modal.spec.js` (new)

**Why the hidden username field:** password managers decide between "Save password?" (new credential) and "Update password?" by finding an `autocomplete="username"` field in the same form as the `new-password` fields. Without one, Chrome/Safari file the submitted password as a new login for the site — the behaviour RM reported. The field is visually hidden, read-only, and excluded from tab order. The login form additionally gets `name`/`autocomplete` so managers learn which credential belongs to this site in the first place.

- [ ] **Step 1: Failing tests**

`ChangePasswordModal.test.js` (mock `api.post`; mock `@/stores/messages.js` `showSuccess`):
```js
it('renders a dialog with a hidden username field and the three password fields', async () => {
  const { findByRole, container } = render(ChangePasswordModal, { props: { open: true, username: 'rachel' } });
  const dialog = await findByRole('dialog', { name: 'Change password' });
  const u = container.querySelector('input[autocomplete="username"]');
  expect(u.value).toBe('rachel');
  expect(u).toHaveAttribute('name', 'username');
  expect(within(dialog).getByLabelText('Current password')).toHaveAttribute('autocomplete', 'current-password');
  expect(within(dialog).getByLabelText('New password')).toHaveAttribute('name', 'new_password');
});
it('posts and closes on success', async () => {
  api.post.mockResolvedValue({});
  const onClose = vi.fn();
  const { findByRole, getByLabelText } = render(ChangePasswordModal, { props: { open: true, username: 'rachel', onClose } });
  await findByRole('dialog');
  await fireEvent.input(getByLabelText('Current password'), { target: { value: 'old' } });
  await fireEvent.input(getByLabelText('New password'), { target: { value: 'newpass1' } });
  await fireEvent.input(getByLabelText('Confirm new password'), { target: { value: 'newpass1' } });
  await fireEvent.click(getByRole('button', { name: 'Change password' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/auth/me/password/', { current_password: 'old', new_password: 'newpass1', new_password_confirm: 'newpass1' }));
  expect(showSuccess).toHaveBeenCalledWith('Password changed.');
  expect(onClose).toHaveBeenCalled();
});
it('shows field errors and stays open', async () => { /* 400 { current_password: ['Wrong password.'] } → text visible, onClose not called */ });
```
`ResetPasswordModal.test.js`: same shape — `user: { id: 4, username: 'sam' }`, dialog 'Reset password', hidden username `sam`, posts `/api/users/4/reset-password/` with `{ password, password_confirm }`, `showSuccess('Password reset.')`.
`LoginPage.test.js`: `it('marks the fields for password managers', …)` → `#username` has `autocomplete="username"` and `name="username"`; `#password` has `autocomplete="current-password"`.
Run → FAIL.

- [ ] **Step 2: Write `ChangePasswordModal.svelte`**
```svelte
<script>
  // Self-service password change, behind a button on the Profile tab (RM
  // 2026-10-10: changing a password is security-notable, so it gets its
  // own modal rather than a form sitting open on the page).
  //
  // The hidden username field is what makes browsers offer "Update
  // password for rachel?" instead of "Save password?" — password managers
  // pair new-password fields with an autocomplete="username" field in the
  // same form. It is read-only, out of the tab order, and visually hidden.
  import { api } from '../../lib/api.js';
  import { fieldErrors } from '../../lib/formErrors.js';
  import { showSuccess } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';

  let { open = false, username = '', onClose = () => {} } = $props();

  let form = $state({ current_password: '', new_password: '', new_password_confirm: '' });
  let errors = $state({});
  let saving = $state(false);

  $effect(() => { if (open) { form = { current_password: '', new_password: '', new_password_confirm: '' }; errors = {}; saving = false; } });

  async function handleSubmit(e) {
    e.preventDefault();
    errors = {}; saving = true;
    try {
      await api.post('/api/auth/me/password/', { ...form });
      showSuccess('Password changed.');
      onClose();
    } catch (err) {
      errors = (err.data && typeof err.data === 'object') ? err.data
        : { non_field_errors: ['Could not change password. Please try again.'] };
    } finally { saving = false; }
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="480px" label="Change password">
  <h3 class="modal-title">Change password</h3>
  <form onsubmit={handleSubmit}>
    <input type="text" name="username" autocomplete="username" value={username}
      readonly tabindex="-1" aria-hidden="true" class="pm-username">
    <p>
      <label for="pw-current"><strong>Current password</strong></label><br>
      <input type="password" id="pw-current" name="current_password" autocomplete="current-password" bind:value={form.current_password} required>
    </p>
    {#each fieldErrors(errors, 'current_password') as msg}<p>{msg}</p>{/each}
    <p>
      <label for="pw-new"><strong>New password</strong></label><br>
      <input type="password" id="pw-new" name="new_password" autocomplete="new-password" bind:value={form.new_password} required>
    </p>
    {#each fieldErrors(errors, 'new_password') as msg}<p>{msg}</p>{/each}
    <p>
      <label for="pw-new-confirm"><strong>Confirm new password</strong></label><br>
      <input type="password" id="pw-new-confirm" name="new_password_confirm" autocomplete="new-password" bind:value={form.new_password_confirm} required>
    </p>
    {#each fieldErrors(errors, 'new_password_confirm') as msg}<p>{msg}</p>{/each}
    {#each fieldErrors(errors, 'non_field_errors') as msg}<p>{msg}</p>{/each}
    <p>
      <button type="submit" disabled={saving}>{saving ? 'Changing...' : 'Change password'}</button>
      <button type="button" onclick={onClose} disabled={saving}>Cancel</button>
    </p>
  </form>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
  /* Present for password managers, invisible to people. */
  .pm-username { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
</style>
```
`ResetPasswordModal.svelte`: props `{ open, user, onClose }`; fields `New password` (`name="password"`, `autocomplete="new-password"`, id `reset-pw`) and `Confirm new password` (`name="password_confirm"`, id `reset-pw-confirm`); hidden username `value={user?.username ?? ''}`; POST `/api/users/${user.id}/reset-password/`; `showSuccess('Password reset.')`; submit label "Reset password"; label "Reset password"; heading `Reset password for {user?.username}`.

- [ ] **Step 3: Hosts**
`ProfilePanel.svelte`: delete `pwForm/pwErrors/pwMessage/pwSaving` and `changePassword`; replace the `<h3>Change password</h3><form>…</form>` block with
```svelte
<h3>Password</h3>
<p><button type="button" onclick={() => { pwOpen = true; }}>Change password…</button></p>
<ChangePasswordModal open={pwOpen} username={$user?.username ?? ''} onClose={() => { pwOpen = false; }} />
```
(`let pwOpen = $state(false);`). Rewrite the ProfilePanel test "changes the password and clears the form" to: click "Change password…" → dialog → fill → "Change password" → `api.post` called with the body → dialog gone.
`UserDetailPage.svelte`: delete `pwForm/pwErrors/pwMessage/pwSaving` + `resetPassword`; replace the Reset password `<form>` with `<p><button type="button" onclick={() => { resetOpen = true; }}>Reset password…</button></p><ResetPasswordModal open={resetOpen} {user} onClose={() => { resetOpen = false; }} />`. Add a UserDetailPage test: "Reset password… opens the reset modal for this user".
`LoginPage.svelte`: `<input id="username" name="username" type="text" autocomplete="username" …>`, `<input id="password" name="password" type="password" autocomplete="current-password" …>`.

- [ ] **Step 4: Run** `cd frontend && npx vitest run tests/components/users tests/components/home tests/routes/LoginPage.test.js tests/components/LoginPage.test.js` → PASS.

- [ ] **Step 5: E2E** `e2e/specs/home/change-password-modal.spec.js` (`personas.worker`): `/#/profile` → "Change password…" → `dialog` 'Change password' visible → fill current `e2e_password`, new `Mismatch1`, confirm `Mismatch2` → "Change password" → dialog still visible (server rejected; the persona's password is unchanged) → Cancel → no dialog. Do **not** change a persona's real password (later specs reuse the saved session, but `auth.setup` would break on the next run). Run → PASS.

- [ ] **Step 6: Commit** — `feat(users): password change/reset behind buttons in modals; username field so browsers offer "update" not "save"`.

---

### Task 16: Final verification sweep

- [ ] **Step 1:** `cd frontend && npm run test:run` — read the summary line; every file passes.
- [ ] **Step 2:** `cd frontend && npm run build` — succeeds.
- [ ] **Step 3:** `grep -rn "ContactFormPage\|BusinessFormPage\|JobFormPage\|UserCreatePage\|EmailCreateJobPage\|EmailAssociatePage\|EmailAssociatePOPage\|EstimateSendPage\|InvoiceSendPage\|ChangeOrderSendPage" frontend/src frontend/tests e2e` — zero hits.
- [ ] **Step 4:** `grep -rn 'href="#/\(contacts\|businesses\|jobs\|users\)/new\|/send"' frontend/src` — only `purchase-orders` hits remain (parked).
- [ ] **Step 5:** `cd e2e && npx playwright test` — full suite, read the summary. Fix anything the per-task runs missed before moving on.
- [ ] **Step 6:** No commit needed unless fixes were made; if so, `fix(ui): …` with the Co-Authored-By line.

---

### Task 17: Documentation

**Files:** `docs/designs/contacts-and-businesses.md`, `docs/designs/jobs-and-tasks.md`, `docs/designs/users-and-permissions.md`, `docs/designs/architecture-and-conventions.md`, `docs/designs/invoicing-and-expenses.md`, `docs/designs/estimates-and-prices.md`, `docs/designs/quickbooks-integration.md`, `docs/designs/materials-inventory-and-purchasing.md`, `docs/designs/LATER.md`, `frontend/README.md`, `CLAUDE.md`, `docs/ui-flows/README.md`, `docs/ui-flows/Change-Orders.md`, `docs/ui-flows/Inventory.md`, `docs/ui-flows/Deposits.md`, `docs/ui-flows/Invoice-Seeding-and-Send.md`

- [ ] **Step 1: contacts-and-businesses.md** — Routes table (§Frontend): `/contacts/new`, `/:id/edit`, `/businesses/new`, `/:id/edit` rows → "redirect stubs (`RedirectTo`); the forms are `ContactFormModal` / `BusinessFormModal`, opened from the list's New buttons, the detail page's Edit, and a business page's New Contact". §Forms: rewrite for the modals; §Duplicate detection → Frontend: the notices are `DuplicateContactNotice` / `DuplicateBusinessNotice` fragments rendered as an in-modal sub-state (form hidden, Escape backs out one level); the `*Modal` wrappers remain only for `EmailCreatePOPage`. "New Contact / New Business links live here" → buttons.
- [ ] **Step 2: jobs-and-tasks.md:1140-1150** — the board's New Job is a button opening `JobCreateModal`; `/jobs/new` redirects to the board; the contact/business pages' New Job pre-select the customer via `defaultContactId`.
- [ ] **Step 3: users-and-permissions.md:342-343, 376** — `/users/new` row → redirect, `UserCreateModal` from the users list; `/users/:id` "Independent sub-forms (Profile, Permissions, Reset password …)" → Reset password is `ResetPasswordModal` behind a button; §376 ProfilePanel: password change is `ChangePasswordModal`; add a short "Password managers" note (the hidden `autocomplete="username"` field + login form `name`/`autocomplete`).
- [ ] **Step 4: architecture-and-conventions.md** — §7.12 "SPA send pages" → "Send modal": `DocumentSendModal` props, hosts, `beforeSubmit`, the dropped doc-ref summary, `/…/send` routes redirect (PO send page unchanged, parked); §7.13 reply composer: now a modal; route list at ~1614-1617: the three email routes redirect to `/email/:id`, with `EmailCreateJobModal` / `EmailLinkModal` hosted by `EmailDetailPage`; add `RedirectTo` next to `JobRedirectToOverview` wherever that is described; the "links navigate / buttons act" exception for send buttons is retired.
- [ ] **Step 5: invoicing-and-expenses.md:1467-1550, 2031, 2062** — `InvoiceSendPage` → `DocumentSendModal` hosted by `InvoicePanel`; the deposit-credit confirm lives in `InvoicePanel.confirmDepositCredits` passed as `beforeSubmit`; expenses: list/home use `ExpenseModal`; reimbursement batch form is a modal.
- [ ] **Step 6: estimates-and-prices.md:2165-2166, 3211, 3324, 3352, 3655** — Send Email / Resend Email open `DocumentSendModal`; `ChangeOrderSendPage` → modal; `CODeliverablesSection` drafting is a modal (Qty/Units/Description), no inline rows.
- [ ] **Step 7: quickbooks-integration.md:492** — "Send Invoice" link → button opening the send modal.
- [ ] **Step 8: materials-inventory-and-purchasing.md:1665, 1696** — `ServiceItemManager` form is a modal; catalog merge/write-off are modals.
- [ ] **Step 9: LATER.md** — confirm the "Service Item edit should be a modal" entry is gone (Task 11); update the `#/jobs` entry (`JobFormPage`'s Cancel no longer exists — the plain list is now reachable only by URL/PM links; keep the item, fix the wording).
- [ ] **Step 10: frontend/README.md** — Modals section: add a "Sub-state, not stacking" paragraph (the duplicate-notice pattern, `hidden` not `{#if}`, `onCancel` backs out one level) and the "create navigates / edit stays / cancel stays" rule; §413 route-category note: the form/send pages are gone.
- [ ] **Step 11: CLAUDE.md** — UI Decisions → "Links navigate; buttons act": delete the standing send-button exception (the send step is now a modal, so the rule holds without exception). URL Structure → Svelte SPA line: forms are modals; mention `RedirectTo` for retired routes.
- [ ] **Step 12: ui-flows** — README rows 37/59/60/62: drop the `/new`, `/edit`, `/send` paths and say "(modal)"; `Change-Orders.md:69,192`, `Inventory.md:103,119`, `Deposits.md:125,143`, `Invoice-Seeding-and-Send.md:229`: "send page" → "send modal", "write-off panel" / "Merge items opens the panel" → "modal".
- [ ] **Step 13: Delete the disposable plan docs** — `git rm docs/plans/2026-10-10-inputs-to-modals-inventory.md docs/plans/2026-10-10-inputs-to-modals-plan.md` (the inventory's durable content now lives in the docs above).
- [ ] **Step 14: Commit** — `docs: record the inputs-to-modals pass (forms, send, password, deliverables, catalog, settings)`.

Then stop: tell RM the branch `feature/ui` is ready for review in the browser. Do not merge, push, or open a PR.
