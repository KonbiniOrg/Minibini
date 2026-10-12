<script>
  // Shown on a job/PO whose contact (or vendor) is inactive — the record is
  // frozen server-side (spec §5); this is the UI's whole treatment plus the
  // one escape hatch, the same-business contact swap.
  let { kind = 'job', partyName, partyHref, businessName = null, businessActive = false, onChangeContact = null } = $props();
  const noun = $derived(kind === 'po' ? 'purchase order' : 'job');
</script>

<div class="frozen-banner" role="status">
  <strong>Frozen:</strong>
  <span><a href={partyHref}>{partyName}</a> is inactive.</span>
  {#if businessActive && businessName && onChangeContact}
    <span>Reactivate them, or move this {noun} to another contact at {businessName}.</span>
    <button type="button" class="edit-link" onclick={onChangeContact}>Change contact…</button>
  {:else}
    <span>Reactivate them before making changes to this {noun}.</span>
  {/if}
</div>

<style>
  .frozen-banner { background: #e0e7ff; border: 1px solid #a5b4fc; color: #3730a3; border-radius: 8px;
    padding: 8px 12px; font-size: 13px; margin: 8px 0 4px; display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; }
  .frozen-banner button { margin-left: auto; }
</style>
