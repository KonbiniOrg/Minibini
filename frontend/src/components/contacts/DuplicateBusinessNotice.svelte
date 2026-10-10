<script>
  // The duplicate-business SUB-STATE of a create modal — sibling of
  // DuplicateContactNotice; see its header comment for the pattern.
  const {
    business = null,
    onViewExisting = () => {},
    onBack = () => {},
  } = $props();
</script>

<h3 class="dup-title">This business may already exist</h3>

{#if business}
  <p>A business with this name is already in the system:</p>
  <p>
    <strong>{business.business_name}</strong><br>
    {#if business.our_reference_code}
      {business.our_reference_code}<br>
    {/if}
    {#if business.business_phone}
      {business.business_phone}<br>
    {/if}
  </p>
{/if}

<p>
  <button type="button" onclick={onViewExisting}>View Existing Business</button>
  <button type="button" onclick={onBack}>Go Back and Edit</button>
</p>

<style>
  .dup-title { margin: 0 0 12px; font-size: 16px; }
</style>
