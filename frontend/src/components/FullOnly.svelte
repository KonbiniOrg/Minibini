<script>
  import { viewMode } from '../stores/viewMode.js';
  const { children } = $props();
</script>

{#if $viewMode === 'full'}
  {@render children()}
{/if}
