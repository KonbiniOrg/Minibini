<script>
  let {
    lineItem = null,
    onAddSelected = () => {},
    onRemoveSource = () => {},
    canAddHere = false,
  } = $props();
</script>

<fieldset>
  <legend>
    <strong>Line {lineItem.line_number}</strong>
    &mdash; ${lineItem.price} × {lineItem.qty} {lineItem.units}
  </legend>

  <p>{lineItem.description || '(no description)'}</p>

  {#if lineItem.sources && lineItem.sources.length > 0}
    <p><strong>Sources ({lineItem.sources.length}):</strong></p>
    <ul>
      {#each lineItem.sources as src (src.source_id)}
        <li>
          [{src.source_type}] #{src.source_pk}
          <button type="button" onclick={() => onRemoveSource(src.source_id)}>
            Remove
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  <p>
    <button
      type="button"
      onclick={() => onAddSelected(lineItem.line_item_id)}
      disabled={!canAddHere}
    >
      Add selected atoms here
    </button>
  </p>
</fieldset>
