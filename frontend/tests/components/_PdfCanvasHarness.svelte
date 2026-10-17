<script>
  // Test-only harness: holds the canvas's bound layout / footer in $state
  // (so the canvas redraws after its own edits, as it does under
  // DocumentPdfSettings) and mirrors every change into `holder` for the
  // test to read.
  import PdfCanvas from '@/components/settings/PdfCanvas.svelte';
  let { holder, ...rest } = $props();
  let layout = $state(holder.layout);
  let footer = $state(holder.footer);
  $effect(() => { holder.layout = $state.snapshot(layout); });
  $effect(() => { holder.footer = footer; });
</script>

<PdfCanvas bind:layout bind:footer {...rest} />
