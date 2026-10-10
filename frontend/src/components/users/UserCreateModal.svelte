<script>
  // Admin "New user" form in Modal over the users list (replaces
  // routes/users/UserCreatePage, 2026-10-10). Lands on the new user's
  // detail page on success. The username input carries
  // autocomplete="username" so a password manager pairs it with the
  // new-password fields instead of filing a nameless credential.
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { fieldErrors } from '../../lib/formErrors.js';
  import Modal from '../Modal.svelte';

  let { open = false, onClose = () => {} } = $props();

  function emptyForm() {
    return { username: '', email: '', first_name: '', last_name: '', password: '', password_confirm: '' };
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
      const created = await api.post('/api/users/', { ...form });
      onClose();
      push(`/users/${created.id}`);
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        errors = err.data;
      } else {
        errors = { non_field_errors: ['Could not create user. Please try again.'] };
      }
    } finally {
      saving = false;
    }
  }
</script>

<!-- Enter is owned by the native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="520px" label="New user">
  <h3 class="modal-title">New user</h3>
  <form onsubmit={handleSubmit}>
    <p>
      <label for="new-username"><strong>Username *</strong></label><br>
      <input type="text" id="new-username" name="username" autocomplete="username" bind:value={form.username} required>
    </p>
    {#each fieldErrors(errors, 'username') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="new-email"><strong>Email *</strong></label><br>
      <input type="email" id="new-email" name="email" bind:value={form.email} required>
    </p>
    {#each fieldErrors(errors, 'email') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="new-first-name"><strong>First name *</strong></label><br>
      <input type="text" id="new-first-name" name="first_name" bind:value={form.first_name} required>
    </p>
    {#each fieldErrors(errors, 'first_name') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="new-last-name"><strong>Last name *</strong></label><br>
      <input type="text" id="new-last-name" name="last_name" bind:value={form.last_name} required>
    </p>
    {#each fieldErrors(errors, 'last_name') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="new-password"><strong>Password *</strong></label><br>
      <input type="password" id="new-password" name="password" autocomplete="new-password" bind:value={form.password} required>
    </p>
    {#each fieldErrors(errors, 'password') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="new-password-confirm"><strong>Confirm password *</strong></label><br>
      <input type="password" id="new-password-confirm" name="password_confirm" autocomplete="new-password" bind:value={form.password_confirm} required>
    </p>
    {#each fieldErrors(errors, 'password_confirm') as msg}<p>{msg}</p>{/each}

    {#each fieldErrors(errors, 'non_field_errors') as msg}<p>{msg}</p>{/each}

    <p>
      <button type="submit" disabled={saving}>{saving ? 'Creating...' : 'Create user'}</button>
      <button type="button" onclick={onClose} disabled={saving}>Cancel</button>
    </p>
  </form>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
