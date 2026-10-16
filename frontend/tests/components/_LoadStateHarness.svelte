<script>
  // Test-only harness so a .js test can pass children to LoadState.
  import LoadState from '@/components/LoadState.svelte';
  let { loading = false, error = null, loadingText = undefined } = $props();
</script>

<LoadState {loading} {error} {loadingText}>
  <p data-testid="content">Loaded content</p>
</LoadState>
