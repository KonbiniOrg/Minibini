<script>
  // Caption row introducing a line's atom child rows — "based on 2 tasks:" —
  // so the grey rows beneath a document line visibly belong to its "Based
  // on" chip. Renders nothing when the line has no sources.
  let { sources = [], colspanBefore = 0, colspan = 1 } = $props();

  const KIND_NOUNS = {
    task: 'task',
    material: 'material',
    expense: 'expense',
    deposit: 'deposit',
  };

  const label = $derived.by(() => {
    const kinds = new Set(sources.map((s) => s.source_type));
    const noun = kinds.size === 1 ? (KIND_NOUNS[[...kinds][0]] || 'item') : 'item';
    const n = sources.length;
    return `based on ${n} ${noun}${n === 1 ? '' : 's'}:`;
  });
</script>

{#if sources.length > 0}
  <tr class="doc-atom-caption">
    {#each Array(colspanBefore) as _}
      <td></td>
    {/each}
    <td {colspan}>{label}</td>
  </tr>
{/if}
