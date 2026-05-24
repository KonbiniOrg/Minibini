<script>
  import { api } from '../../lib/api.js';

  let workday_start = $state('08:00');
  let workday_end = $state('17:00');
  let task_buffer_minutes = $state('10');
  let horizon_days = $state('3');
  let saveMessage = $state('');
  let errors = $state({});

  async function load() {
    try {
      const data = await api.get('/api/settings/');
      workday_start = data.schedule_workday_start ?? '08:00';
      workday_end = data.schedule_workday_end ?? '17:00';
      task_buffer_minutes = data.schedule_task_buffer_minutes ?? '10';
      horizon_days = data.schedule_horizon_days ?? '3';
    } catch (_) {}
  }

  async function save() {
    saveMessage = '';
    errors = {};
    try {
      await api.patch('/api/settings/', {
        schedule_workday_start: workday_start,
        schedule_workday_end: workday_end,
        schedule_task_buffer_minutes: task_buffer_minutes,
        schedule_horizon_days: horizon_days,
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
<p>Controls the layout of the /schedule view: working hours, buffer between
tasks, and the default rolling-day horizon.</p>

<fieldset>
  <legend><strong>Working day</strong></legend>
  <p><label><strong>Work day start</strong></label><br>
    <input type="time" bind:value={workday_start}>
    {#if errors.schedule_workday_start}<em class="err">{errors.schedule_workday_start}</em>{/if}
  </p>
  <p><label><strong>Work day end</strong></label><br>
    <input type="time" bind:value={workday_end}>
    {#if errors.schedule_workday_end}<em class="err">{errors.schedule_workday_end}</em>{/if}
  </p>
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
</fieldset>

<p>
  <button type="button" onclick={save}>Save</button>
  {#if saveMessage}<em>{saveMessage}</em>{/if}
  {#if errors._general}<em class="err">{errors._general}</em>{/if}
</p>

<style>
  .err { color: #b91c1c; margin-left: 0.5em; }
</style>
