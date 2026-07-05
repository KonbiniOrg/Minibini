<script>
  // The single global instance of the red/green message overlay (mounted
  // once in App.svelte). Pages raise it via stores/messages.js
  // (showError / showSuccess) instead of carrying their own overlay markup.
  // CSS classes live in css/app.css (shared with nothing else now).
  import { overlayMessage, clearMessage } from '../stores/messages.js';
</script>

{#if $overlayMessage}
  {@const kind = $overlayMessage.kind}
  <div class={kind === 'error' ? 'error-overlay' : 'success-overlay'}>
    <div class={kind === 'error' ? 'error-overlay-content' : 'success-overlay-content'}>
      <button
        class={kind === 'error' ? 'error-overlay-close' : 'success-overlay-close'}
        onclick={clearMessage}
        aria-label="Dismiss message"
      >&times;</button>
      <p><strong>{kind === 'error' ? 'Error:' : ''}</strong> {$overlayMessage.text}</p>
    </div>
  </div>
{/if}
