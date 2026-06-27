<script>
  import { api } from '../lib/api.js';

  let { open = false, onselect, onfreeform, onclose } = $props();

  let services = $state([]);
  let materials = $state([]);
  let q = $state('');
  let loaded = $state(false);

  async function load() {
    const [svc, inv] = await Promise.all([
      api.get('/api/service-items/?task_applicable=true'),
      api.get('/api/inventory/?is_active=true'),
    ]);
    services = (svc.results || svc).map((s) => ({
      kind: 'service', id: s.service_item_id, label: s.name,
      sub: s.description || '', price: s.rate, item: s,
    }));
    materials = (inv.results || inv)
      .filter((m) => m.is_catalog)
      .map((m) => ({
        kind: 'material', id: m.inventory_item_id, label: m.code,
        sub: m.description || '', price: m.selling_price, item: m,
      }));
    loaded = true;
  }

  $effect(() => { if (open && !loaded) load(); });

  const rows = $derived(
    [...services, ...materials].filter((r) => {
      const t = q.trim().toLowerCase();
      return !t || r.label.toLowerCase().includes(t) || r.sub.toLowerCase().includes(t);
    })
  );
</script>

{#if open}
  <div class="overlay" role="dialog" aria-label="Add from Price List">
    <div class="modal">
      <header>
        <h3>Add from Price List</h3>
        <button type="button" onclick={() => onclose?.()}>Close</button>
      </header>
      <!-- svelte-ignore a11y_autofocus -->
      <input type="search" placeholder="Search price list…" bind:value={q} autofocus />
      <ul>
        {#each rows as r (r.kind + r.id)}
          <li>
            <button type="button" onclick={() => onselect?.({ kind: r.kind, item: r.item })}>
              <span class="label">{r.label}</span>
              {#if r.sub}<span class="sub">{r.sub}</span>{/if}
              {#if r.price}<span class="price">${r.price}</span>{/if}
            </button>
          </li>
        {/each}
      </ul>
      <footer>
        <button type="button" onclick={() => onfreeform?.()}>+ Freeform material</button>
      </footer>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: var(--z-modal);
  }
  .modal {
    background: white; padding: 16px; max-width: 560px; width: 90%;
    border: 1px solid #ccc; display: flex; flex-direction: column; gap: 10px;
  }
  header { display: flex; align-items: center; justify-content: space-between; }
  h3 { margin: 0; }
  input[type="search"] { width: 100%; box-sizing: border-box; padding: 6px 8px; font-size: 1rem; }
  ul { list-style: none; margin: 0; padding: 0; max-height: 340px; overflow-y: auto; border: 1px solid #e0e0e0; }
  li button {
    width: 100%; text-align: left; background: none; border: none;
    padding: 8px 10px; cursor: pointer; display: flex; gap: 12px; align-items: baseline;
  }
  li button:hover { background: #f5f5f5; }
  /* fixed-width label column so every row's description starts at the same x */
  .label { font-weight: 500; flex: 0 0 12rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { color: #666; font-size: 0.875rem; flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .price { color: #333; font-size: 0.875rem; white-space: nowrap; margin-left: auto; }
  footer { border-top: 1px solid #e0e0e0; padding-top: 8px; }
  footer button { background: none; border: none; cursor: pointer; color: #555; padding: 4px 0; }
  footer button:hover { color: #000; }
</style>
