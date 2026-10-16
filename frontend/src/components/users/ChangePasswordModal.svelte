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
  import { triageError } from '../../lib/errorTriage.js';
  import { showSuccess, showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';

  let { open = false, username = '', onClose = () => {} } = $props();

  function emptyForm() {
    return { current_password: '', new_password: '', new_password_confirm: '' };
  }
  let form = $state(emptyForm());
  let errors = $state({});
  let saving = $state(false);

  $effect(() => { if (open) { form = emptyForm(); errors = {}; saving = false; } });

  async function handleSubmit(e) {
    e.preventDefault();
    errors = {};
    saving = true;
    try {
      await api.post('/api/auth/me/password/', { ...form });
      showSuccess('Password changed.');
      onClose();
    } catch (err) {
      // Field errors land under their inputs; an operation error ({detail})
      // lands in the footer; infrastructure errors go to the global overlay.
      const t = triageError(err);
      if (t.overlay) showError(t.overlay);
      else errors = { ...t.fields, ...(t.message ? { non_field_errors: [t.message] } : {}) };
    } finally {
      saving = false;
    }
  }
</script>

<!-- Enter is owned by the native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="480px" label="Change password">
  <h3 class="modal-title">Change password</h3>
  <form onsubmit={handleSubmit}>
    <input type="text" name="username" autocomplete="username" value={username}
      readonly tabindex="-1" aria-hidden="true" class="pm-username">
    <p>
      <label for="pw-current"><strong>Current password</strong></label><br>
      <input type="password" id="pw-current" name="current_password" autocomplete="current-password"
        bind:value={form.current_password} required>
    </p>
    {#each fieldErrors(errors, 'current_password') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="pw-new"><strong>New password</strong></label><br>
      <input type="password" id="pw-new" name="new_password" autocomplete="new-password"
        bind:value={form.new_password} required>
    </p>
    {#each fieldErrors(errors, 'new_password') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="pw-new-confirm"><strong>Confirm new password</strong></label><br>
      <input type="password" id="pw-new-confirm" name="new_password_confirm" autocomplete="new-password"
        bind:value={form.new_password_confirm} required>
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
