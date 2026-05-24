<script>
  // Renders free text with http(s):// URLs (dotted host) turned into clickable
  // links, and everything else as plain auto-escaped text. Renders inline with
  // no wrapper element, so drop it inside an existing `.preserve-breaks` wrapper
  // (a <p>, <td>, <dd>, …) to inherit newline preservation and long-token wrap:
  //
  //   <p class="preserve-breaks"><LinkifiedText text={job.description} /></p>
  import { linkify } from '../lib/linkify.js';

  let { text = '' } = $props();
  let segments = $derived(linkify(text));
</script>
{#each segments as seg}{#if seg.type === 'url'}<a href={seg.href} title={seg.value} target="_blank" rel="noopener noreferrer">{seg.display}</a>{:else}{seg.value}{/if}{/each}

<style>
  /* Long links wrap mid-URL rather than forcing their container wide. */
  a { overflow-wrap: anywhere; }
</style>
