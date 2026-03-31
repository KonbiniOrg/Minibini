<script>
  import { api } from '../lib/api.js';

  let units = $state([]);
  let newUnit = $state('');
  let error = $state('');
  let saving = $state(false);
  let loading = $state(true);

  async function loadUnits() {
    try {
      units = await api.get('/api/settings/units/');
    } catch (e) {
      error = 'Failed to load units.';
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
      error = e.data?.error || e.message || 'Failed to save.';
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
    if (units[index] === 'none') return;
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
<p>Manage the list of available units. Removing a unit does not update existing records — they keep their current value, but the unit won't be available for selection going forward unless re-added.</p>

{#if error}
  <p><strong>Error:</strong> {error}</p>
{/if}

{#if loading}
  <p>Loading...</p>
{:else}
  <table>
    <thead>
      <tr>
        <th>Unit</th>
        <th>Order</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each units as unit, i}
        <tr>
          <td>{unit}</td>
          <td>
            {#if i > 1}
              <button onclick={() => moveUp(i)} disabled={saving}>↑</button>
            {/if}
            {#if i > 0 && i < units.length - 1}
              <button onclick={() => moveDown(i)} disabled={saving}>↓</button>
            {/if}
          </td>
          <td>
            {#if unit !== 'none'}
              <button onclick={() => removeUnit(i)} disabled={saving}>Remove</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <p>
    <input
      type="text"
      bind:value={newUnit}
      placeholder="New unit name"
      onkeydown={(e) => { if (e.key === 'Enter') addUnit(); }}
    />
    <button onclick={addUnit} disabled={saving || !newUnit.trim()}>Add</button>
  </p>
{/if}
