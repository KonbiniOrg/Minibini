<script>
  // POs section body. Job owned by JobWorkspace. (Was JobPOsPage.)
  import POPanel from '../../../components/purchaseorders/POPanel.svelte';
  let { job } = $props();
</script>

<POPanel {job} />
