<script>
  // One shape for the loading / error / content branch that every fetch site
  // used to hand-write (docs/designs/architecture-and-conventions.md §3.9 for
  // the error-text contract). State stays in the caller:
  //
  //   <LoadState {loading} {error} loadingText="Searching...">
  //     …content…
  //   </LoadState>
  //
  // `error` must already be display text (route it through errorMessage() in
  // the catch block); this component never inspects an Error object.
  let {
    loading = false,
    error = null,
    loadingText = 'Loading...',
    children,
  } = $props();
</script>

{#if loading}
  <p class="load-state loading">{loadingText}</p>
{:else if error}
  <p class="load-state error" role="alert">{error}</p>
{:else}
  {@render children?.()}
{/if}
