<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { fieldErrors } from '../../lib/formErrors.js';

  let form = $state({
    username: '',
    email: '',
    first_name: '',
    last_name: '',
    password: '',
    password_confirm: '',
  });
  let errors = $state({});
  let saving = $state(false);

  async function handleSubmit(e) {
    e.preventDefault();
    errors = {};
    saving = true;
    try {
      const created = await api.post('/api/users/', form);
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

<h2>New user</h2>

<form onsubmit={handleSubmit}>
  <p>
    <label for="new-username"><strong>Username *</strong></label><br>
    <input type="text" id="new-username" bind:value={form.username} required>
  </p>
  {#each fieldErrors(errors, 'username') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-email"><strong>Email *</strong></label><br>
    <input type="email" id="new-email" bind:value={form.email} required>
  </p>
  {#each fieldErrors(errors, 'email') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-first-name"><strong>First name *</strong></label><br>
    <input type="text" id="new-first-name" bind:value={form.first_name} required>
  </p>
  {#each fieldErrors(errors, 'first_name') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-last-name"><strong>Last name *</strong></label><br>
    <input type="text" id="new-last-name" bind:value={form.last_name} required>
  </p>
  {#each fieldErrors(errors, 'last_name') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-password"><strong>Password *</strong></label><br>
    <input
      type="password"
      id="new-password"
      autocomplete="new-password"
      bind:value={form.password}
      required
    >
  </p>
  {#each fieldErrors(errors, 'password') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-password-confirm"><strong>Confirm password *</strong></label><br>
    <input
      type="password"
      id="new-password-confirm"
      autocomplete="new-password"
      bind:value={form.password_confirm}
      required
    >
  </p>
  {#each fieldErrors(errors, 'password_confirm') as msg}
    <p>{msg}</p>
  {/each}

  {#each fieldErrors(errors, 'non_field_errors') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <button type="submit" disabled={saving}>
      {saving ? 'Creating...' : 'Create user'}
    </button>
    <a href="/users" use:link>Cancel</a>
  </p>
</form>
