<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let { rateSchemeId = $bindable(''), activeModifiers = $bindable([]), estQty = $bindable('') } = $props();

  let schemes = $state([]);
  let loading = $state(true);
  let error = $state('');

  onMount(async () => {
    try {
      const resp = await api.get('/api/rate-schemes/');
      schemes = resp.results || resp;
    } catch (e) {
      error = e.message || 'Could not load rate schemes.';
    } finally {
      loading = false;
    }
  });

  let selectedScheme = $derived(
    schemes.find(s => s.rate_scheme_id === Number(rateSchemeId)) || null
  );

  function toggleModifier(key, checked) {
    if (checked) {
      if (!activeModifiers.includes(key)) {
        activeModifiers = [...activeModifiers, key];
      }
    } else {
      activeModifiers = activeModifiers.filter(k => k !== key);
    }
  }
</script>

{#if loading}
  <p>Loading rate schemes…</p>
{:else if error}
  <p style="color: red;">{error}</p>
{:else}
  <p>
    <label for="rate-scheme"><strong>Rate scheme *</strong></label><br>
    <select id="rate-scheme" bind:value={rateSchemeId} required>
      <option value="">-- select --</option>
      {#each schemes as s (s.rate_scheme_id)}
        <option value={s.rate_scheme_id}>{s.name}</option>
      {/each}
    </select>
  </p>

  {#if selectedScheme}
    <p>
      <strong>{selectedScheme.name}</strong> — ${selectedScheme.rate}/{selectedScheme.unit_label}
    </p>

    {#if selectedScheme.modifiers && selectedScheme.modifiers.length > 0}
      <fieldset>
        <legend><strong>Modifiers</strong></legend>
        {#each selectedScheme.modifiers as m (m.key)}
          <p>
            <label>
              <input
                type="checkbox"
                checked={activeModifiers.includes(m.key)}
                onchange={(e) => toggleModifier(m.key, e.target.checked)}
              />
              {m.label} (+{m.percent}%)
            </label>
          </p>
        {/each}
      </fieldset>
    {/if}

    <p>
      <label for="est-qty"><strong>Estimated qty *</strong></label><br>
      <input
        id="est-qty"
        type="number"
        step="0.01"
        bind:value={estQty}
        required
      />
    </p>
  {/if}
{/if}
