<script>
  import { api } from '../lib/api.js';

  let {
    onSelect = () => {},
    disabled = false,
    placeholder = 'Search catalogs…',
  } = $props();

  let query = $state('');
  let taskTemplates = $state([]);
  let priceListItems = $state([]);
  let showDropdown = $state(false);
  let loading = $state(false);

  // Combined, filtered, tagged results — task templates and PLIs interleaved.
  let results = $derived.by(() => {
    const lower = query.toLowerCase();
    const tts = taskTemplates
      .filter(t => !lower
        || t.template_name.toLowerCase().includes(lower)
        || (t.description || '').toLowerCase().includes(lower))
      .map(t => ({
        kind: 'task_template',
        id: t.template_id,
        label: t.template_name,
        sub: t.description || '',
        meta: t.rate ? `$${t.rate}/${t.units}` : '',
        item: t,
      }));
    const plis = priceListItems
      .filter(p => !lower
        || p.code.toLowerCase().includes(lower)
        || (p.description || '').toLowerCase().includes(lower))
      .map(p => ({
        kind: 'inventory_item',
        id: p.inventory_item_id,
        label: p.code,
        sub: p.description || '',
        meta: `$${p.selling_price}/${p.units}`,
        item: p,
      }));
    return [...tts, ...plis].sort((a, b) => a.label.localeCompare(b.label));
  });

  async function fetchCatalogs() {
    if (taskTemplates.length > 0 && priceListItems.length > 0) return;
    loading = true;
    try {
      const [tts, plis] = await Promise.all([
        api.get('/api/task-templates/?page_size=9999'),
        api.get('/api/inventory/?page_size=9999'),
      ]);
      taskTemplates = tts.results || tts;
      priceListItems = plis.results || plis;
    } catch (e) {
      taskTemplates = [];
      priceListItems = [];
    } finally {
      loading = false;
    }
  }

  function handleInput(e) {
    query = e.target.value;
    showDropdown = true;
  }

  function handleFocus() {
    showDropdown = true;
    fetchCatalogs();
  }

  function handleBlur() {
    setTimeout(() => { showDropdown = false; }, 200);
  }

  function pick(result) {
    showDropdown = false;
    query = '';
    onSelect({kind: result.kind, item: result.item});
  }

  function pickManual() {
    showDropdown = false;
    query = '';
    onSelect({kind: 'manual', item: null});
  }
</script>

<div class="catalog-picker">
  <input
    type="text"
    {placeholder}
    {disabled}
    value={query}
    oninput={handleInput}
    onfocus={handleFocus}
    onblur={handleBlur}
  />
  {#if showDropdown}
    <div class="dropdown">
      {#if loading}
        <p class="loading">Loading catalogs…</p>
      {:else}
        {#each results as r (r.kind + ':' + r.id)}
          <button type="button" class="result" onclick={() => pick(r)}>
            <small class="tag">[{r.kind === 'task_template' ? 'task' : 'material'}]</small>
            <strong>{r.label}</strong>
            {#if r.meta}<span class="meta">{r.meta}</span>{/if}
            {#if r.sub}<div class="sub">{r.sub}</div>{/if}
          </button>
        {/each}
        <button type="button" class="result manual" onclick={pickManual}>
          <small class="tag">[manual]</small>
          <strong>Enter manually</strong>
          <div class="sub">Type custom description, qty, and price</div>
        </button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .catalog-picker { position: relative; }
  .catalog-picker input { width: 100%; padding: 0.4rem; }
  .dropdown {
    position: absolute; top: 100%; left: 0; right: 0;
    background: white; border: 1px solid #ccc; max-height: 320px; overflow-y: auto;
    z-index: var(--z-dropdown);
  }
  .result {
    display: block; width: 100%; text-align: left;
    padding: 0.5rem; border: none; background: white; cursor: pointer;
    border-bottom: 1px solid #eee;
  }
  .result:hover { background: #f4f4f4; }
  .result.manual { font-style: italic; }
  .tag { color: #888; margin-right: 0.4rem; }
  .meta { color: #666; margin-left: 0.4rem; }
  .sub { color: #666; font-size: 0.85em; margin-top: 0.2rem; }
  .loading { padding: 0.5rem; color: #888; }
</style>
