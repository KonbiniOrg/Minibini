<script>
  // Admin password reset for another user, behind a button on the user
  // detail page (RM 2026-10-10). Same password-manager hint as
  // ChangePasswordModal: the hidden username is the TARGET user's, so the
  // admin's browser may offer to update its saved credential for that
  // account — accurate, and there is no reliable way to suppress it.
  import { api } from '../../lib/api.js';
  import { fieldErrors } from '../../lib/formErrors.js';
  import { showSuccess } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';

  let { open = false, user = null, onClose = () => {} } = $props();

  function emptyForm() { return { password: '', password_confirm: '' }; }
  let form = $state(emptyForm());
  let errors = $state({});
  let saving = $state(false);

  $effect(() => { if (open) { form = emptyForm(); errors = {}; saving = false; } });

  async function handleSubmit(e) {
    e.preventDefault();
    errors = {};
    saving = true;
    try {
      await api.post(`/api/users/${user.id}/reset-password/`, { ...form });
      showSuccess('Password reset.');
      onClose();
    } catch (err) {
      errors = (err.data && typeof err.data === 'object')
        ? err.data
        : { non_field_errors: ['Could not reset password.'] };
    } finally {
      saving = false;
    }
  }
</script>

<!-- Enter is owned by the native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="480px" label="Reset password">
  <h3 class="modal-title">Reset password for {user?.username ?? ''}</h3>
  <form onsubmit={handleSubmit}>
    <input type="text" name="username" autocomplete="username" value={user?.username ?? ''}
      readonly tabindex="-1" aria-hidden="true" class="pm-username">
    <p>
      <label for="reset-pw"><strong>New password</strong></label><br>
      <input type="password" id="reset-pw" name="password" autocomplete="new-password"
        bind:value={form.password} required>
    </p>
    {#each fieldErrors(errors, 'password') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="reset-pw-confirm"><strong>Confirm new password</strong></label><br>
      <input type="password" id="reset-pw-confirm" name="password_confirm" autocomplete="new-password"
        bind:value={form.password_confirm} required>
    </p>
    {#each fieldErrors(errors, 'password_confirm') as msg}<p>{msg}</p>{/each}
    {#each fieldErrors(errors, 'non_field_errors') as msg}<p>{msg}</p>{/each}

    <p>
      <button type="submit" disabled={saving}>{saving ? 'Resetting...' : 'Reset password'}</button>
      <button type="button" onclick={onClose} disabled={saving}>Cancel</button>
    </p>
  </form>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
  .pm-username { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
</style>
