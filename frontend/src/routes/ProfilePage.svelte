<script>
  import { api } from '../lib/api.js';
  import { user } from '../stores/auth.js';
  import { viewMode, toggleViewMode } from '../stores/viewMode.js';

  let profileForm = $state({
    email: '',
    first_name: '',
    last_name: '',
  });
  let profileErrors = $state({});
  let profileMessage = $state('');
  let profileSaving = $state(false);
  let initialized = $state(false);

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
        profileErrors = { non_field: ['Could not save. Please try again.'] };
      }
    } finally {
      profileSaving = false;
    }
  }

  function fieldErrors(errors, field) {
    const v = errors[field];
    if (!v) return [];
    return Array.isArray(v) ? v : [v];
  }
</script>

<h2>Profile</h2>

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

    {#each fieldErrors(profileErrors, 'non_field') as msg}
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

<h3>Preferences</h3>
<p>
  View mode: <strong>{$viewMode}</strong>
  — <a href="#" onclick={(e) => { e.preventDefault(); toggleViewMode(); }}>
    Switch to {$viewMode === 'full' ? 'lite' : 'full'} view
  </a>
</p>
