<script>
  import { api } from '../../lib/api.js';
  import { fieldErrors } from '../../lib/formErrors.js';
  import { user } from '../../stores/auth.js';
  import { viewMode, toggleViewMode } from '../../stores/viewMode.js';

  let profileForm = $state({
    email: '',
    first_name: '',
    last_name: '',
  });
  let profileErrors = $state({});
  let profileMessage = $state('');
  let profileSaving = $state(false);
  let initialized = $state(false);

  let pwForm = $state({
    current_password: '',
    new_password: '',
    new_password_confirm: '',
  });
  let pwErrors = $state({});
  let pwMessage = $state('');
  let pwSaving = $state(false);

  // Initialize form from the store once, after the user is loaded.
  $effect(() => {
    if (!initialized && $user) {
      profileForm.email = $user.email || '';
      profileForm.first_name = $user.first_name || '';
      profileForm.last_name = $user.last_name || '';
      initialized = true;
    }
  });

  async function saveProfile(e) {
    e.preventDefault();
    profileErrors = {};
    profileMessage = '';
    profileSaving = true;
    try {
      const updated = await api.patch('/api/auth/me/', {
        email: profileForm.email,
        first_name: profileForm.first_name,
        last_name: profileForm.last_name,
      });
      user.set(updated);
      profileMessage = 'Saved.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        profileErrors = err.data;
      } else {
        profileErrors = { non_field_errors: ['Could not save. Please try again.'] };
      }
    } finally {
      profileSaving = false;
    }
  }

  async function changePassword(e) {
    e.preventDefault();
    pwErrors = {};
    pwMessage = '';
    pwSaving = true;
    try {
      await api.post('/api/auth/me/password/', pwForm);
      pwForm.current_password = '';
      pwForm.new_password = '';
      pwForm.new_password_confirm = '';
      pwMessage = 'Password changed.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        pwErrors = err.data;
      } else {
        pwErrors = { non_field_errors: ['Could not change password. Please try again.'] };
      }
    } finally {
      pwSaving = false;
    }
  }

</script>

<h3>Account info</h3>

{#if !$user}
  <p>Loading...</p>
{:else}
  <form onsubmit={saveProfile}>
    <p>
      <strong>Username:</strong> {$user.username}
    </p>

    <p>
      <label for="profile-email"><strong>Email</strong></label><br>
      <input
        type="email"
        id="profile-email"
        bind:value={profileForm.email}
      >
    </p>
    {#each fieldErrors(profileErrors, 'email') as msg}
      <p>{msg}</p>
    {/each}

    <p>
      <label for="profile-first-name"><strong>First name</strong></label><br>
      <input
        type="text"
        id="profile-first-name"
        bind:value={profileForm.first_name}
      >
    </p>
    {#each fieldErrors(profileErrors, 'first_name') as msg}
      <p>{msg}</p>
    {/each}

    <p>
      <label for="profile-last-name"><strong>Last name</strong></label><br>
      <input
        type="text"
        id="profile-last-name"
        bind:value={profileForm.last_name}
      >
    </p>
    {#each fieldErrors(profileErrors, 'last_name') as msg}
      <p>{msg}</p>
    {/each}

    {#each fieldErrors(profileErrors, 'non_field_errors') as msg}
      <p>{msg}</p>
    {/each}

    <p>
      <button type="submit" disabled={profileSaving}>
        {profileSaving ? 'Saving...' : 'Save'}
      </button>
    </p>
    {#if profileMessage}
      <p>{profileMessage}</p>
    {/if}
  </form>
{/if}

<h3>Change password</h3>
<form onsubmit={changePassword}>
  <p>
    <label for="pw-current"><strong>Current password</strong></label><br>
    <input
      type="password"
      id="pw-current"
      autocomplete="current-password"
      bind:value={pwForm.current_password}
    >
  </p>
  {#each fieldErrors(pwErrors, 'current_password') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="pw-new"><strong>New password</strong></label><br>
    <input
      type="password"
      id="pw-new"
      autocomplete="new-password"
      bind:value={pwForm.new_password}
    >
  </p>
  {#each fieldErrors(pwErrors, 'new_password') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="pw-new-confirm"><strong>Confirm new password</strong></label><br>
    <input
      type="password"
      id="pw-new-confirm"
      autocomplete="new-password"
      bind:value={pwForm.new_password_confirm}
    >
  </p>
  {#each fieldErrors(pwErrors, 'new_password_confirm') as msg}
    <p>{msg}</p>
  {/each}

  {#each fieldErrors(pwErrors, 'non_field_errors') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <button type="submit" disabled={pwSaving}>
      {pwSaving ? 'Changing...' : 'Change password'}
    </button>
  </p>
  {#if pwMessage}
    <p>{pwMessage}</p>
  {/if}
</form>

<h3>Preferences</h3>
<p>
  View mode: <strong>{$viewMode}</strong>
  — <button type="button" onclick={toggleViewMode}>
    Switch to {$viewMode === 'full' ? 'lite' : 'full'} view
  </button>
</p>
