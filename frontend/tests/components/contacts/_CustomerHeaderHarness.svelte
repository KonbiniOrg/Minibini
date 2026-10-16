<script>
  // Mounts CustomerHeader with an `actions` snippet (tests can't pass snippets
  // as plain props).
  import CustomerHeader from '@/components/contacts/CustomerHeader.svelte';
  let { onNewJob = () => {}, ...rest } = $props();
</script>

<CustomerHeader {...rest}>
  {#snippet actions()}
    <button type="button" class="banner-btn" onclick={onNewJob}>New Job</button>
    <button type="button" class="edit-link header-action">Edit</button>
  {/snippet}
</CustomerHeader>
