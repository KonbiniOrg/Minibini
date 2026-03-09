<script>
  const { business, onEdit = null, onDelete = null } = $props();
</script>

<dl>
  <dt>Reference Code</dt>
  <dd>{business.our_reference_code}</dd>

  <dt>Name</dt>
  <dd>{business.business_name}</dd>

  <dt>Phone</dt>
  <dd>{business.business_phone}</dd>

  <dt>Address</dt>
  <dd>{business.business_address}</dd>

  <dt>Website</dt>
  <dd>{business.website}</dd>

  <dt>Tax Exemption</dt>
  <dd>{business.tax_exemption_number || "(Not exempt)"}</dd>

  <dt>Tax Multiplier</dt>
  <dd>{business.tax_multiplier ?? '(full rate)'}</dd>

  <dt>Payment Terms</dt>
  <dd>{business.terms || 'None'}</dd>

  <dt>Default Contact</dt>
  <dd><a href="#/contacts/{business.default_contact.contact_id}">{business.default_contact.name}</a></dd>
</dl>

<p>
  {#if onEdit}
    <button onclick={onEdit}>Edit</button>
  {/if}
  {#if onDelete}
    <button onclick={onDelete}>Delete</button>
  {/if}
</p>
