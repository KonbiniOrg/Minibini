<script>
  // Dual-source picker for the worksheet/estimate atom-add flow.
  // Shows service items (task-applicable) and catalog inventory items together,
  // driven by backend search (no initial list — results appear after typing).
  // Props mirror the consumption side in WorksheetDetailPage / estimate forms.
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  import { PICKER_PAGE_SIZE } from '../lib/pagination.js';

  let { open = false, onselect = null, oncustomtask = null, onfreeform = null, onclose = null } = $props();

  const search = async (q) => {
    const enc = encodeURIComponent(q);
    const [svc, inv] = await Promise.all([
      api.get(`/api/service-items/?search=${enc}&page_size=${PICKER_PAGE_SIZE}`),
      api.get(`/api/inventory/?is_active=true&is_catalog=true&search=${enc}&page_size=${PICKER_PAGE_SIZE}`),
    ]);
    const svcRows = svc.results || svc;
    const invRows = inv.results || inv;
    const rows = [
      ...svcRows.map((s) => ({
        kind: 'service',
        id: s.template_id,
        label: s.template_name,
        sub: s.description || '',
        price: s.rate_scheme_detail?.rate,
        unit: s.rate_scheme_detail?.unit_label,
        item: s,
      })),
      ...invRows.map((m) => ({
        kind: 'material',
        id: m.inventory_item_id,
        label: m.code,
        sub: m.description || '',
        price: m.selling_price,
        unit: m.units,
        item: m,
      })),
    ];
    return {
      rows,
      total: (svc.count ?? svcRows.length) + (inv.count ?? invRows.length),
    };
  };

  const rowLabel = (r) => r.label;
  const resolveLabel = () => Promise.resolve(null);
</script>

{#if open}
  <div class="plp-overlay" role="dialog" aria-modal="true">
    <div class="plp-modal">
      <div class="plp-header">
        <strong>Add item</strong>
        <button type="button" onclick={onclose}>Close</button>
      </div>

      <div class="plp-body">
        <SearchPicker
          {search}
          {resolveLabel}
          {rowLabel}
          onPick={(r) => onselect?.({ kind: r.kind, item: r.item })}
          placeholder="Search services or materials…"
        >
          {#snippet row(r)}
            <span class="plp-row">
              <span class="plp-row-label">{r.label}</span>
              <span class="plp-row-sub">{r.sub}</span>
              {#if r.price != null}
                <span class="plp-row-price">${Number(r.price).toFixed(2)}</span>
              {/if}
              {#if r.unit}<span class="plp-row-unit">/ {r.unit}</span>{/if}
            </span>
          {/snippet}
        </SearchPicker>
      </div>

      <div class="plp-footer">
        <button type="button" onclick={oncustomtask}>Add custom task</button>
        <button type="button" onclick={onfreeform}>Add freeform material</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .plp-overlay {
    position: fixed; inset: 0; background: rgba(0, 0, 0, 0.4);
    display: flex; align-items: flex-start; justify-content: center;
    padding-top: 80px; z-index: var(--z-modal);
  }
  .plp-modal {
    background: white; border: 1px solid #ccc; width: 560px; max-width: 95vw;
    display: flex; flex-direction: column;
  }
  .plp-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; border-bottom: 1px solid #eee;
  }
  .plp-body { padding: 12px 14px; position: relative; }
  /* Widen the search box to ~2x a default text input. Scoped under .plp-body so
     other SearchPicker instances elsewhere are unaffected. */
  .plp-body :global(input[type="text"]) { width: 40ch; max-width: 100%; }
  .plp-footer { padding: 10px 14px; border-top: 1px solid #eee; }

  /* Row layout inside SearchPicker's dropdown button (which is display:block,
     so the row needs its own flex container for the columns to align) */
  .plp-row { display: flex; gap: 12px; align-items: baseline; width: 100%; }
  .plp-row-label { flex: 0 0 12rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .plp-row-sub {
    flex: 1 1 auto; min-width: 0; color: #666; font-size: 12px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .plp-row-price { margin-left: auto; font-size: 12px; color: #444; white-space: nowrap; }
  .plp-row-unit { font-size: 12px; color: #777; white-space: nowrap; }
</style>
