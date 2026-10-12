<script>
  // The duplicate-detection SUB-STATE of a create modal (RM 2026-10-10:
  // sub-state, not a stacked modal). The host renders this in place of its
  // form while keeping the form mounted-but-hidden, so "Go Back and Edit"
  // returns to every value the user typed. No <Modal> here — the host owns
  // the shell and backs out one level on Escape.
  const {
    contact = null,
    onViewExisting = () => {},
    onBack = () => {},
    onReactivate = null,
  } = $props();
</script>

<h3 class="dup-title">This contact may already exist</h3>

{#if contact}
  <p>A contact with this email address is already in the system:</p>
  <p>
    <strong>{contact.name}</strong>
    {#if contact.is_active === false}<span class="status-badge status-inactive">inactive</span>{/if}<br>
    {contact.email}<br>
    {#if contact.phones?.[0]?.number}
      {contact.phones[0].number}<br>
    {/if}
    {#if contact.business}
      {contact.business.business_name}
    {/if}
  </p>
{/if}

<p>
  <button type="button" onclick={onViewExisting}>View Existing Contact</button>
  {#if contact?.is_active === false && onReactivate}<button type="button" onclick={onReactivate}>Reactivate</button>{/if}
  <button type="button" onclick={onBack}>Go Back and Edit</button>
</p>

<style>
  .dup-title { margin: 0 0 12px; font-size: 16px; }
</style>
