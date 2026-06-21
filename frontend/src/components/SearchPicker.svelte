<script>
  // Behavior core for entity type-ahead pickers. Owns the interaction:
  // debounced search, the focus/blur results dropdown, prefill-by-id label
  // resolution (with a race guard), and the selected/clear state. It is
  // deliberately ignorant of endpoints and entity shapes — those arrive via
  // the `search` / `resolveLabel` / `rowLabel` callbacks and the snippets.
  let {
    value = $bindable(null),       // opaque selection token (id, or {type,id})
    selectedItem = null,           // optional prefill object, passed to resolveLabel
    search,                        // (query) => Promise<row[]>
    resolveLabel,                  // (value, selectedItem?) => Promise<string|null>
    rowLabel = (r) => String(r),   // (row) => string
    onPick = () => {},             // (row) => void  — parent sets `value`
    onClear = () => {},            // () => void     — parent clears `value`
    disabled = false,
    placeholder = 'Search…',
    row,                           // optional snippet(item)
    selected,                      // optional snippet(label)
    header,                        // optional snippet(close)
  } = $props();

  let query = $state('');
  let results = $state([]);
  let showResults = $state(false);
  let selectedLabel = $state('');
  let labelForValue = $state(null); // which `value` selectedLabel describes
  let timer = null;

  function runSearch() {
    const q = query.trim();
    if (!q) { results = []; showResults = false; return; }
    Promise.resolve(search(q))
      .then((rows) => { results = rows || []; showResults = true; })
      .catch((e) => console.error(e));
  }

  function onInput(e) {
    query = e.target.value;
    clearTimeout(timer);
    timer = setTimeout(runSearch, 250);
  }

  function onFocus() { if (query.trim()) showResults = true; }
  function onBlur() { setTimeout(() => { showResults = false; }, 200); }
  function close() { showResults = false; query = ''; results = []; }

  function pick(r) {
    close();
    onPick(r);              // parent assigns `value` synchronously
    selectedLabel = rowLabel(r);
    labelForValue = value;  // now matches the just-assigned value
  }

  function clear() {
    close();
    selectedLabel = '';
    labelForValue = null;
    onClear();              // parent sets value = null
  }

  // Prefill / external value changes: resolve a display label once per value.
  $effect(() => {
    const v = value;
    if (v == null) { selectedLabel = ''; labelForValue = null; return; }
    if (v === labelForValue) return; // already labelled (race guard)
    Promise.resolve(resolveLabel(v, selectedItem))
      .then((lbl) => { if (value === v) { selectedLabel = lbl || ''; labelForValue = v; } })
      .catch(() => {});
  });
</script>

{#if value != null && labelForValue === value}
  {#if selected}
    {@render selected(selectedLabel)}
  {:else}
    <span class="sp-selected">{selectedLabel}
      <button type="button" onclick={clear} disabled={disabled}>Clear</button>
    </span>
  {/if}
{:else}
  <input type="text" value={query} oninput={onInput} onfocus={onFocus}
         onblur={onBlur} {disabled} {placeholder}>
  {#if showResults}
    <ul class="sp-results" role="listbox">
      {#if header}{@render header(close)}{/if}
      {#if results.length}
        {#each results as r}
          <li>
            <button type="button" onclick={() => pick(r)}>
              {#if row}{@render row(r)}{:else}{rowLabel(r)}{/if}
            </button>
          </li>
        {/each}
      {:else}
        <li class="sp-empty">No matches.</li>
      {/if}
    </ul>
  {/if}
{/if}

<style>
  .sp-results { position: absolute; background: white; border: 1px solid #ccc;
    max-height: 220px; overflow-y: auto; z-index: var(--z-dropdown); margin: 0;
    padding: 0; list-style: none; min-width: 16rem; }
  .sp-results li button { display: block; width: 100%; text-align: left;
    background: none; border: none; padding: 6px 8px; cursor: pointer; font-size: 13px; }
  .sp-results li button:hover { background: #eef; }
  .sp-empty { padding: 6px 8px; color: #777; font-size: 13px; }
  .sp-selected { font-size: 14px; }
</style>
