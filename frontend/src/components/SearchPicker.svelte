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
    query = $bindable(''),         // current search text (bindable so callers can reuse it)
  } = $props();

  import { tick } from 'svelte';

  let results = $state([]);
  let total = $state(0);            // total matches available (for the truncation hint)
  let showResults = $state(false);
  let selectedLabel = $state('');
  let labelForValue = $state(null); // which `value` selectedLabel describes
  let highlighted = $state(-1);     // arrow-key cursor into `results`; -1 = none
  let listEl = $state(null);
  let timer = null;

  // `search` may return a plain row[] or { rows, total }. Normalize both so the
  // dropdown can show "showing N of M" when the result set is capped.
  function runSearch() {
    const q = query.trim();
    if (!q) { results = []; total = 0; showResults = false; return; }
    Promise.resolve(search(q))
      .then((res) => {
        results = Array.isArray(res) ? res : (res?.rows ?? []);
        total = Array.isArray(res) ? res.length : (res?.total ?? results.length);
        showResults = true;
        highlighted = -1;   // fresh results, fresh cursor
      })
      .catch((e) => console.error(e));
  }

  function onInput(e) {
    query = e.target.value;
    clearTimeout(timer);
    timer = setTimeout(runSearch, 250);
  }

  function onFocus() { if (query.trim()) showResults = true; }
  function onBlur() { setTimeout(() => { showResults = false; highlighted = -1; }, 200); }
  function close() { showResults = false; query = ''; results = []; total = 0; highlighted = -1; }

  // Arrow keys walk the dropdown; Enter picks the highlighted row (and only
  // then — without a highlight it keeps its native meaning, submitting the
  // enclosing form); Escape closes just the dropdown first, and only a second
  // press reaches the modal's window listener to close the modal.
  function onKeydown(e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!showResults) { if (query.trim()) showResults = true; return; }
      if (!results.length) return;
      e.preventDefault();
      const delta = e.key === 'ArrowDown' ? 1 : -1;
      highlighted = (highlighted + delta + results.length) % results.length;
      tick().then(() => {
        listEl?.querySelector('.sp-highlighted')?.scrollIntoView?.({ block: 'nearest' });
      });
    } else if (e.key === 'Enter') {
      if (showResults && highlighted >= 0 && highlighted < results.length) {
        e.preventDefault();      // don't submit the enclosing form
        e.stopPropagation();     // don't reach a shell-level onSave either
        pick(results[highlighted]);
      }
    } else if (e.key === 'Escape') {
      if (showResults) {
        e.preventDefault();
        e.stopPropagation();     // first Esc: dropdown only, modal stays
        showResults = false;
        highlighted = -1;
      }
    }
  }

  let pendingLabel = null; // label captured at pick time, applied when value updates

  function pick(r) {
    close();
    pendingLabel = rowLabel(r);
    onPick(r); // parent updates `value` (synchronously or batched)
  }

  function clear() {
    close();
    pendingLabel = null;
    selectedLabel = '';
    labelForValue = null;
    onClear(); // parent sets value = null
  }

  // Apply the picked/prefilled label once `value` settles.
  $effect(() => {
    const v = value;
    if (v == null) { selectedLabel = ''; labelForValue = null; pendingLabel = null; return; }
    if (v === labelForValue) return; // already labelled (race guard)
    if (pendingLabel != null) {      // just picked locally — no fetch needed
      selectedLabel = pendingLabel;
      labelForValue = v;
      pendingLabel = null;
      return;
    }
    Promise.resolve(resolveLabel(v, selectedItem))
      .then((lbl) => { if (value === v) { selectedLabel = lbl || ''; labelForValue = v; } })
      .catch(() => {});
  });

  $effect(() => () => clearTimeout(timer));
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
         onblur={onBlur} onkeydown={onKeydown} {disabled} {placeholder}
         aria-autocomplete="list" aria-expanded={showResults}>
  {#if showResults}
    <ul class="sp-results" role="listbox" bind:this={listEl}>
      {#if header}{@render header(close)}{/if}
      {#if results.length}
        {#each results as r, i}
          <li role="option" aria-selected={i === highlighted}>
            <button type="button" class:sp-highlighted={i === highlighted}
                    onmousedown={() => pick(r)}>
              {#if row}{@render row(r)}{:else}{rowLabel(r)}{/if}
            </button>
          </li>
        {/each}
        {#if total > results.length}
          <li class="sp-more">showing {results.length} of {total} — keep typing to narrow</li>
        {/if}
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
  .sp-results li button:hover, .sp-results li button.sp-highlighted { background: #eef; }
  .sp-empty { padding: 6px 8px; color: #777; font-size: 13px; }
  .sp-more { padding: 6px 8px; color: #777; font-size: 12px; font-style: italic; }
  .sp-selected { font-size: 14px; }
</style>
