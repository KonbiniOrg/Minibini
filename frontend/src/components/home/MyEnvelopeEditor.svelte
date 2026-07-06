<script>
  // A worker's own weekly schedule envelope (Home → Time, bottom). Null =
  // following the shop schedule. Explicit Save commits via the self-service
  // endpoint; edits are local until then.
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../../lib/api.js';
  import EnvelopeEditor from '../schedule/EnvelopeEditor.svelte';

  let envelope = $state(null);
  let loaded = $state(false);
  let dirty = $state(false);
  let saveMessage = $state('');
  let error = $state('');

  onMount(async () => {
    try {
      const me = await api.get('/api/auth/me/');
      envelope = me.schedule_envelope ?? null;
    } catch (_) {}
    loaded = true;
  });

  function handleChange(next) {
    envelope = next;
    dirty = true;
    saveMessage = '';
  }

  async function save() {
    error = '';
    saveMessage = '';
    try {
      await api.put('/api/auth/me/schedule-envelope/', {
        schedule_envelope: envelope,
      });
      dirty = false;
      saveMessage = 'Schedule saved.';
    } catch (e) {
      error = errorMessage(e, 'Could not save your schedule.');
    }
  }
</script>

<section class="my-envelope">
  <h3>My schedule</h3>
  {#if loaded}
    <EnvelopeEditor value={envelope} allowNull={true} onchange={handleChange} />
    <p>
      <button type="button" onclick={save} disabled={!dirty}>Save</button>
      {#if saveMessage}<em>{saveMessage}</em>{/if}
      {#if error}<em class="err">{error}</em>{/if}
    </p>
  {:else}
    <p>Loading…</p>
  {/if}
</section>

<style>
  .my-envelope { margin-top: 1.5em; }
  .err { color: #b91c1c; margin-left: 0.5em; }
</style>
