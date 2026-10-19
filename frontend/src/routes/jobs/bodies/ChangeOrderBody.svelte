<script>
  // Change-order section body. Job owned by JobWorkspace. The route always
  // carries :coId (the estimate section handles "which document" defaulting),
  // so there is no docId resolution here. Nav rail shows the estimate section
  // active. (Was JobChangeOrderPage.)
  import ChangeOrderPanel from '../../../components/changeorders/ChangeOrderPanel.svelte';
  let { params = {}, job, onJobChange = () => {} } = $props();
  const coId = $derived(params.coId);
</script>

<ChangeOrderPanel {job} {coId} {onJobChange} />
