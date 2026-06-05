<script>
  // Test-only wrapper. Accordion requires a `children` snippet (`{@render
  // children()}`), which a plain .js test can't easily construct — so we wrap it
  // in a tiny .svelte harness that supplies real child markup. The vitest include
  // glob only collects *.test.js, so this .svelte file is never run as a test;
  // it's just imported by Accordion.test.js.
  import Accordion from '@/components/Accordion.svelte';
  let { open = false } = $props();
</script>

<Accordion title="Details" {open}>
  <p>body content</p>
</Accordion>
