<script>
  // Shipments section body. Job owned by JobWorkspace. (Was JobShipmentsPage.)
  import ShipmentsPanel from '../../../components/shipments/ShipmentsPanel.svelte';
  let { job, onJobChange = () => {} } = $props();
</script>

<ShipmentsPanel {job} {onJobChange} />
