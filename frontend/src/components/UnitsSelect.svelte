<!-- frontend/src/components/UnitsSelect.svelte -->
<script>
  import { api } from '../lib/api.js';

  let {
    value = $bindable('none'),
    name = 'units',
    id = '',
    disabled = false,
    onchange = undefined,
  } = $props();

  let units = $state([]);
  let loading = $state(true);

  async function loadUnits() {
    try {
      units = await api.get('/api/settings/units/');
    } catch (e) {
      units = ['none'];
    } finally {
      loading = false;
    }
  }

  loadUnits();
</script>

<select
  {name}
  id={id || name}
  bind:value
  {disabled}
  {onchange}
>
  {#each units as unit}
    <option value={unit}>{unit}</option>
  {/each}
</select>
