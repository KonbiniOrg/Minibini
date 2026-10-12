<script>
  import PhoneListEditor from '@/components/contacts/PhoneListEditor.svelte';
  let { phones = [], errors = {} } = $props();
  // svelte-ignore state_referenced_locally -- mount-seed by design
  let list = $state(phones);
</script>
<PhoneListEditor bind:phones={list} {errors} />
<span data-testid="bound">{list.map((p) => p.number).join(',')}</span>
