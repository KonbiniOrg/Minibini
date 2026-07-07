<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as currentUser } from '../../stores/auth.js';
  import { fieldErrors } from '../../lib/formErrors.js';
  import UserReimbursementPanel from '../../components/expenses/UserReimbursementPanel.svelte';
  import EnvelopeEditor from '../../components/schedule/EnvelopeEditor.svelte';
  import WorkSessionsList from '../../components/time/WorkSessionsList.svelte';

  const { params = {} } = $props();

  const ATOMS = [
    { codename: 'can_manage_jobs', label: 'Can manage jobs' },
    { codename: 'can_manage_financials', label: 'Can manage financials' },
    { codename: 'can_manage_time', label: 'Can manage time entries' },
    { codename: 'can_manage_config', label: 'Can manage configuration (user admin)' },
  ];

  let user = $state(null);
  let loading = $state(true);
  let loadError = $state('');

  let profileForm = $state({ username: '', email: '', first_name: '', last_name: '' });
  let profileErrors = $state({});
  let profileMessage = $state('');
  let profileSaving = $state(false);

  let permForm = $state({ permissions: [] });
  let permErrors = $state({});
  let permMessage = $state('');
  let permSaving = $state(false);

  let pwForm = $state({ password: '', password_confirm: '' });
  let pwErrors = $state({});
  let pwMessage = $state('');
  let pwSaving = $state(false);

  let statusErrors = $state({});
  let statusMessage = $state('');
  let statusSaving = $state(false);

  let envForm = $state({ schedule_envelope: null });
  let envDirty = $state(false);
  let envErrors = $state({});
  let envMessage = $state('');
  let envSaving = $state(false);

  let isSelf = $derived(
    $currentUser && user && $currentUser.id === user.id
  );

  async function load() {
    loading = true;
    loadError = '';
    try {
      user = await api.get(`/api/users/${params.id}/`);
      seedFormsFromUser();
    } catch (err) {
      loadError = err.message || 'Could not load user.';
    } finally {
      loading = false;
    }
  }

  function seedFormsFromUser() {
    profileForm.username = user.username || '';
    profileForm.email = user.email || '';
    profileForm.first_name = user.first_name || '';
    profileForm.last_name = user.last_name || '';
    permForm.permissions = [...(user.permissions || [])];
    envForm.schedule_envelope = user.schedule_envelope ?? null;
    envDirty = false;
  }

  async function saveEnvelope(e) {
    e.preventDefault();
    envErrors = {};
    envMessage = '';
    envSaving = true;
    try {
      const updated = await api.put(
        `/api/users/${user.id}/schedule-envelope/`,
        { schedule_envelope: envForm.schedule_envelope }
      );
      user = updated;
      envForm.schedule_envelope = user.schedule_envelope ?? null;
      envDirty = false;
      envMessage = 'Schedule saved.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        envErrors = err.data;
      } else {
        envErrors = { non_field_errors: ['Could not save the schedule.'] };
      }
    } finally {
      envSaving = false;
    }
  }

  async function saveProfile(e) {
    e.preventDefault();
    profileErrors = {};
    profileMessage = '';
    profileSaving = true;
    try {
      const updated = await api.patch(`/api/users/${user.id}/`, profileForm);
      user = updated;
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

  function togglePerm(codename) {
    if (permForm.permissions.includes(codename)) {
      permForm.permissions = permForm.permissions.filter((c) => c !== codename);
    } else {
      permForm.permissions = [...permForm.permissions, codename];
    }
  }

  async function savePermissions(e) {
    e.preventDefault();
    permErrors = {};
    permMessage = '';
    permSaving = true;
    try {
      const updated = await api.put(
        `/api/users/${user.id}/permissions/`,
        { permissions: permForm.permissions }
      );
      user = updated;
      permForm.permissions = [...(user.permissions || [])];
      permMessage = 'Permissions saved.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        permErrors = err.data;
      } else {
        permErrors = { non_field_errors: ['Could not save permissions.'] };
      }
    } finally {
      permSaving = false;
    }
  }

  async function resetPassword(e) {
    e.preventDefault();
    pwErrors = {};
    pwMessage = '';
    pwSaving = true;
    try {
      await api.post(`/api/users/${user.id}/reset-password/`, pwForm);
      pwForm.password = '';
      pwForm.password_confirm = '';
      pwMessage = 'Password reset.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        pwErrors = err.data;
      } else {
        pwErrors = { non_field_errors: ['Could not reset password.'] };
      }
    } finally {
      pwSaving = false;
    }
  }

  async function toggleStatus() {
    statusErrors = {};
    statusMessage = '';
    statusSaving = true;
    const actionUrl = user.is_active ? 'deactivate' : 'activate';
    try {
      const updated = await api.post(`/api/users/${user.id}/${actionUrl}/`);
      user = updated;
      statusMessage = user.is_active ? 'User activated.' : 'User deactivated.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        statusErrors = err.data;
      } else {
        statusErrors = { non_field_errors: ['Could not change status.'] };
      }
    } finally {
      statusSaving = false;
    }
  }

  $effect(() => {
    // Re-load if the route param changes
    void params.id;
    load();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p>{loadError}</p>
  <p><a href="/users" use:link>← Back to users</a></p>
{:else if user}
  <h2>User: {user.username}</h2>
  <p>
    <a href="/users" use:link>← Back to users</a>
  </p>

  <p>
    Status:
    {#if user.is_active}
      <strong>Active</strong>
    {:else}
      <em>Deactivated</em>
    {/if}
  </p>

  <h3>Profile</h3>
  <form onsubmit={saveProfile}>
    <p>
      <label for="prof-username"><strong>Username</strong></label><br>
      <input type="text" id="prof-username" bind:value={profileForm.username}>
    </p>
    {#each fieldErrors(profileErrors, 'username') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="prof-email"><strong>Email</strong></label><br>
      <input type="email" id="prof-email" bind:value={profileForm.email}>
    </p>
    {#each fieldErrors(profileErrors, 'email') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="prof-first"><strong>First name</strong></label><br>
      <input type="text" id="prof-first" bind:value={profileForm.first_name}>
    </p>
    {#each fieldErrors(profileErrors, 'first_name') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="prof-last"><strong>Last name</strong></label><br>
      <input type="text" id="prof-last" bind:value={profileForm.last_name}>
    </p>
    {#each fieldErrors(profileErrors, 'last_name') as msg}<p>{msg}</p>{/each}

    {#each fieldErrors(profileErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}

    <p>
      <button type="submit" disabled={profileSaving}>
        {profileSaving ? 'Saving...' : 'Save profile'}
      </button>
    </p>
    {#if profileMessage}<p>{profileMessage}</p>{/if}
  </form>

  <h3>Permissions</h3>
  <form onsubmit={savePermissions}>
    {#each ATOMS as atom (atom.codename)}
      <p>
        <label>
          <input
            type="checkbox"
            checked={permForm.permissions.includes(atom.codename)}
            onchange={() => togglePerm(atom.codename)}
            disabled={
              isSelf
                && atom.codename === 'can_manage_config'
                && permForm.permissions.includes('can_manage_config')
            }
          >
          <strong>{atom.label}</strong>
        </label>
      </p>
    {/each}
    {#each fieldErrors(permErrors, 'permissions') as msg}<p>{msg}</p>{/each}
    {#each fieldErrors(permErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}
    <p>
      <button type="submit" disabled={permSaving}>
        {permSaving ? 'Saving...' : 'Save permissions'}
      </button>
    </p>
    {#if permMessage}<p>{permMessage}</p>{/if}
  </form>

  <h3>Reset password</h3>
  <form onsubmit={resetPassword}>
    <p>
      <label for="reset-pw"><strong>New password</strong></label><br>
      <input
        type="password"
        id="reset-pw"
        autocomplete="new-password"
        bind:value={pwForm.password}
      >
    </p>
    {#each fieldErrors(pwErrors, 'password') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="reset-pw-confirm"><strong>Confirm new password</strong></label><br>
      <input
        type="password"
        id="reset-pw-confirm"
        autocomplete="new-password"
        bind:value={pwForm.password_confirm}
      >
    </p>
    {#each fieldErrors(pwErrors, 'password_confirm') as msg}<p>{msg}</p>{/each}

    {#each fieldErrors(pwErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}

    <p>
      <button type="submit" disabled={pwSaving}>
        {pwSaving ? 'Resetting...' : 'Reset password'}
      </button>
    </p>
    {#if pwMessage}<p>{pwMessage}</p>{/if}
  </form>

  <h3>Account status</h3>
  <p>
    <button
      type="button"
      onclick={toggleStatus}
      disabled={statusSaving || (isSelf && user.is_active)}
    >
      {#if user.is_active}
        {isSelf ? 'Deactivate (cannot deactivate yourself)' : (statusSaving ? 'Deactivating...' : 'Deactivate')}
      {:else}
        {statusSaving ? 'Activating...' : 'Reactivate'}
      {/if}
    </button>
  </p>
  {#each fieldErrors(statusErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}
  {#if statusMessage}<p>{statusMessage}</p>{/if}

  <h3>Schedule envelope</h3>
  <form onsubmit={saveEnvelope}>
    <EnvelopeEditor
      value={envForm.schedule_envelope}
      allowNull={true}
      onchange={(v) => { envForm.schedule_envelope = v; envDirty = true; envMessage = ''; }}
    />
    <p>
      <button type="submit" disabled={envSaving || !envDirty}>
        {envSaving ? 'Saving...' : 'Save schedule'}
      </button>
    </p>
    {#each fieldErrors(envErrors, 'schedule_envelope') as msg}<p class="err">{msg}</p>{/each}
    {#each fieldErrors(envErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}
    {#if envMessage}<p>{envMessage}</p>{/if}
  </form>

  <h3>Expenses</h3>
  <UserReimbursementPanel {user} />

  <!-- This user's work sessions (bleps), recent-first, paged; the worker
       column is suppressed — every row is this user. -->
  <WorkSessionsList userId={user.id} />
{/if}
