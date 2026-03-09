<script>
  const { business, onEdit = null, onDelete = null } = $props();
</script>

<dl>
  <dt>Reference Code</dt>
  <dd>{business.our_reference_code}</dd>

  <dt>Name</dt>
  <dd>{business.business_name}</dd>

  {#if business.business_phone}
    <dt>Phone</dt>
    <dd>{business.business_phone}</dd>
  {/if}

  {#if business.business_address}
    <dt>Address</dt>
    <dd>{business.business_address}</dd>
  {/if}

  {#if business.website}
    <dt>Website</dt>
    <dd>{business.website}</dd>
  {/if}

  {#if business.tax_exemption_number}
    <dt>Tax Exemption</dt>
    <dd>{business.tax_exemption_number}</dd>
  {/if}

  <dt>Tax Multiplier</dt>
  <dd>{business.tax_multiplier ?? 'Default (full rate)'}</dd>

  <dt>Payment Terms</dt>
  <dd>{business.terms || 'None'}</dd>

  <dt>Default Contact</dt>
  <dd>{business.default_contact || 'None'}</dd>
</dl>

<p>
  {#if onEdit}
    <button onclick={onEdit}>Edit</button>
  {/if}
  {#if onDelete}
    <button onclick={onDelete}>Delete</button>
  {/if}
</p>
