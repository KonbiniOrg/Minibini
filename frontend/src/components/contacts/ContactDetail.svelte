<script>
  const { contact, onEdit = null, onDelete = null } = $props();
</script>

<dl>
  <dt>Name</dt>
  <dd>{contact.name}</dd>

  <dt>Email</dt>
  <dd>{contact.email}</dd>

  {#if contact.work_number}
    <dt>Work</dt>
    <dd>{contact.work_number}</dd>
  {/if}

  {#if contact.mobile_number}
    <dt>Mobile</dt>
    <dd>{contact.mobile_number}</dd>
  {/if}

  {#if contact.home_number}
    <dt>Home</dt>
    <dd>{contact.home_number}</dd>
  {/if}

  {#if contact.addr1}
    <dt>Address</dt>
    <dd>
      {contact.addr1}
      {#if contact.addr2}<br>{contact.addr2}{/if}
      {#if contact.addr3}<br>{contact.addr3}{/if}
      {#if contact.city}<br>{contact.city}{/if}
      {#if contact.municipality}, {contact.municipality}{/if}
      {#if contact.postal_code} {contact.postal_code}{/if}
      {#if contact.country_code}<br>{contact.country_code}{/if}
    </dd>
  {/if}

  <dt>Business</dt>
  <dd>
    {#if contact.business}
      <a href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>
    {:else}
      None
    {/if}
  </dd>
</dl>

<p>
  {#if onEdit}
    <button onclick={onEdit}>Edit</button>
  {/if}
  {#if onDelete}
    <button onclick={onDelete}>Delete</button>
  {/if}
</p>
