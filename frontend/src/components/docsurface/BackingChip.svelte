<script>
  let { backing, syncedWithEstimate = false } = $props();

  const labelMap = {
    estimate: 'estimate',
    actuals: 'actuals',
    edited: 'edited',
    deposit: 'deposit',
    deposit_credit: 'deposit credit',
    planned_work: 'planned work',
    planned_materials: 'planned materials',
    from_catalog: 'from catalog',
    // "none" not "hand line" — the internal term isn't meaningful to users
    // (RM 2026-08-10): the chip answers "what backs this price?", and for a
    // typed-in line the honest answer is nothing.
    hand: 'none',
    adjustment: 'adjustment',
  };

  const classMap = {
    actuals: 'actuals',
    planned_work: 'planned',
    planned_materials: 'planned',
    from_catalog: 'catalog',
    deposit: 'deposit',
    edited: 'edited',
  };

  let label = $derived.by(() => {
    if (backing === null || backing === undefined) return null;
    if (backing === 'actuals' && syncedWithEstimate) {
      return 'actuals = estimate ✓';
    }
    return labelMap[backing] || backing;
  });

  let cssClass = $derived.by(() => {
    if (backing === null || backing === undefined) return '';
    let cls = '';
    if (backing === 'actuals' && syncedWithEstimate) {
      cls = 'synced';
    } else {
      cls = classMap[backing] || '';
    }
    return cls;
  });
</script>

{#if label !== null}
  <span class="backing-chip {cssClass}">{label}</span>
{/if}
