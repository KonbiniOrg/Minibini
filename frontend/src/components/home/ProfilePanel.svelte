<script>
  import { api } from '../../lib/api.js';
  import { fieldErrors } from '../../lib/formErrors.js';
  import { user } from '../../stores/auth.js';
  import { viewMode, toggleViewMode } from '../../stores/viewMode.js';
  import LoadState from '../LoadState.svelte';
  import ChangePasswordModal from '../users/ChangePasswordModal.svelte';

  let profileForm = $state({
    email: '',
    first_name: '',
    last_name: '',
  });
  let profileErrors = $state({});
  let profileMessage = $state('');
  let profileSaving = $state(false);
  let initialized = $state(false);

  // Password change lives in ChangePasswordModal (2026-10-10).
  let pwOpen = $state(false);

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

</script>

<h3>Account info</h3>

<LoadState loading={!$user}>
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
</LoadState>

<h3>Password</h3>
<p><button type="button" onclick={() => { pwOpen = true; }}>Change password…</button></p>
<ChangePasswordModal open={pwOpen} username={$user?.username ?? ''} onClose={() => { pwOpen = false; }} />

<h3>Preferences</h3>
<p>
  View mode: <strong>{$viewMode}</strong>
  — <button type="button" onclick={toggleViewMode}>
    Switch to {$viewMode === 'full' ? 'lite' : 'full'} view
  </button>
</p>
