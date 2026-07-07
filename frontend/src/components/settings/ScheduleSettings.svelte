<script>
  import { api } from '../../lib/api.js';
  import EnvelopeEditor from '../schedule/EnvelopeEditor.svelte';

  const DEFAULT_ENVELOPE = () => ({
    mon: [['08:00', '17:00']], tue: [['08:00', '17:00']],
    wed: [['08:00', '17:00']], thu: [['08:00', '17:00']],
    fri: [['08:00', '17:00']], sat: [], sun: [],
  });

  let envelope = $state(DEFAULT_ENVELOPE());
  let task_buffer_minutes = $state('10');
  let horizon_days = $state('3');
  let activity_recent_days = $state('5');
  let blep_minimum_minutes = $state('1');
  let saveMessage = $state('');
  let errors = $state({});

  async function load() {
    try {
      const data = await api.get('/api/settings/');
      try {
        envelope = data.schedule_week_envelope
          ? JSON.parse(data.schedule_week_envelope)
          : DEFAULT_ENVELOPE();
      } catch (_) {
        envelope = DEFAULT_ENVELOPE();
      }
      task_buffer_minutes = data.schedule_task_buffer_minutes ?? '10';
      horizon_days = data.schedule_horizon_days ?? '3';
      activity_recent_days = data.activity_recent_days ?? '5';
      blep_minimum_minutes = data.blep_minimum_minutes ?? '1';
    } catch (_) {}
  }

  async function save() {
    saveMessage = '';
    errors = {};
    try {
      await api.patch('/api/settings/', {
        schedule_week_envelope: envelope,
        schedule_task_buffer_minutes: task_buffer_minutes,
        schedule_horizon_days: horizon_days,
        activity_recent_days: activity_recent_days,
        blep_minimum_minutes: blep_minimum_minutes,
      });
      saveMessage = 'Schedule settings saved.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        errors = err.data;
      } else {
        errors = { _general: err.message || 'Save failed' };
      }
    }
  }

  load();
</script>

<h3>Schedule</h3>
<p>Controls the layout of the /schedule view: the shop's working week
(per-day hours, optional breaks, days off), buffer between tasks, and the
default rolling-day horizon. Workers without a personal envelope follow
this week.</p>

<fieldset>
  <legend><strong>Working week</strong></legend>
  <EnvelopeEditor value={envelope} onchange={(v) => { envelope = v; }} />
  {#if errors.schedule_week_envelope}<em class="err">{errors.schedule_week_envelope}</em>{/if}
</fieldset>

<fieldset>
  <legend><strong>Other</strong></legend>
  <p><label><strong>Buffer between tasks (minutes)</strong></label><br>
    <input type="number" min="0" bind:value={task_buffer_minutes}>
    {#if errors.schedule_task_buffer_minutes}<em class="err">{errors.schedule_task_buffer_minutes}</em>{/if}
  </p>
  <p><label><strong>Default horizon (days)</strong></label><br>
    <input type="number" min="1" max="14" bind:value={horizon_days}>
    {#if errors.schedule_horizon_days}<em class="err">{errors.schedule_horizon_days}</em>{/if}
  </p>
  <p><label><strong>Recent activity (days)</strong></label><br>
    <input type="number" min="1" bind:value={activity_recent_days}>
    {#if errors.activity_recent_days}<em class="err">{errors.activity_recent_days}</em>{/if}
  </p>
  <p class="hint">Look-back window for the Activity page (a backward window,
  separate from the forward schedule horizon above).</p>
</fieldset>

<fieldset>
  <legend><strong>Time tracking</strong></legend>
  <p><label><strong>Minimum session (minutes)</strong></label><br>
    <input type="number" min="0" bind:value={blep_minimum_minutes}>
    {#if errors.blep_minimum_minutes}<em class="err">{errors.blep_minimum_minutes}</em>{/if}
  </p>
  <p class="hint">Below this, a worker's <strong>Stop</strong> becomes <strong>Cancel</strong>:
  a just-started session can only be discarded (the task reverts as if it never
  started), not saved.</p>
</fieldset>

<p>
  <button type="button" onclick={save}>Save</button>
  {#if saveMessage}<em>{saveMessage}</em>{/if}
  {#if errors._general}<em class="err">{errors._general}</em>{/if}
</p>

<style>
  .err { color: #b91c1c; margin-left: 0.5em; }
  .hint { font-size: 13px; color: #666; }
</style>
