<script>
  import { api, errorMessage } from '../lib/api.js';
  import LoadState from './LoadState.svelte';
  import DataTable from './DataTable.svelte';

  let units = $state([]);
  let newUnit = $state('');
  let error = $state('');
  let saving = $state(false);
  let loading = $state(true);

  const SPECIAL_UNITS = ['none', 'hour'];  // undeletable; mirror of backend rule

  async function loadUnits() {
    try {
      units = await api.get('/api/settings/units/');
    } catch (e) {
      error = errorMessage(e, 'Failed to load units.');
    } finally {
      loading = false;
    }
  }

  async function saveUnits() {
    saving = true;
    error = '';
    try {
      units = await api.patch('/api/settings/units/', units);
    } catch (e) {
      error = errorMessage(e, 'Failed to save.');
    } finally {
      saving = false;
    }
  }

  function addUnit() {
    const trimmed = newUnit.trim();
    if (!trimmed) return;
    if (units.includes(trimmed)) {
      error = `"${trimmed}" already exists.`;
      return;
    }
    error = '';
    units = [...units, trimmed];
    newUnit = '';
    saveUnits();
  }

  function removeUnit(index) {
    if (SPECIAL_UNITS.includes(units[index])) return;
    units = units.filter((_, i) => i !== index);
    saveUnits();
  }

  function moveUp(index) {
    if (index <= 1) return;  // can't move above "none" at index 0
    const copy = [...units];
    [copy[index - 1], copy[index]] = [copy[index], copy[index - 1]];
    units = copy;
    saveUnits();
  }

  function moveDown(index) {
    if (index === 0 || index >= units.length - 1) return;
    const copy = [...units];
    [copy[index], copy[index + 1]] = [copy[index + 1], copy[index]];
    units = copy;
    saveUnits();
  }

  loadUnits();
</script>

<h3>Units</h3>
<p>Manage the list of available units. Removing a unit does not update existing records — they keep their current value, but the unit won't be available for selection going forward unless re-added. "none" and "hour" are built-in and can't be removed — "hour" is the unit time-based billing and scheduling use.</p>

{#if error}
  <p><strong>Error:</strong> {error}</p>
{/if}

<LoadState {loading}>
  <DataTable
    rows={units}
    key={(unit) => unit}
    columns={[
      { id: 'unit',   label: 'Unit',  cell: unitCell },
      { id: 'order',  label: 'Order', cell: orderCell },
      { id: 'remove', label: '',      cell: removeCell },
    ]}
  />

  <p>
    <input
      type="text"
      bind:value={newUnit}
      placeholder="New unit name"
      onkeydown={(e) => { if (e.key === 'Enter') addUnit(); }}
    />
    <button onclick={addUnit} disabled={saving || !newUnit.trim()}>Add</button>
  </p>
</LoadState>

{#snippet unitCell(unit)}{unit}{/snippet}
{#snippet orderCell(unit)}
  {@const i = units.indexOf(unit)}
  {#if i > 1}
    <button onclick={() => moveUp(i)} disabled={saving}>↑</button>
  {/if}
  {#if i > 0 && i < units.length - 1}
    <button onclick={() => moveDown(i)} disabled={saving}>↓</button>
  {/if}
{/snippet}
{#snippet removeCell(unit)}
  {#if !SPECIAL_UNITS.includes(unit)}
    <button onclick={() => removeUnit(units.indexOf(unit))} disabled={saving}>Remove</button>
  {/if}
{/snippet}
