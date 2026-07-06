<script>
  // The single global instance of the red/green message overlay (mounted
  // once in App.svelte). Pages raise it via stores/messages.js
  // (showError / showSuccess) instead of carrying their own overlay markup.
  // CSS classes live in css/app.css (shared with nothing else now).
  import { overlayMessage, clearMessage } from '../stores/messages.js';
</script>

{#if $overlayMessage}
  {@const kind = $overlayMessage.kind}
  <!-- Backdrop click dismisses (target check so clicks inside the box don't);
       the X button remains for keyboard/AT users. -->
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class={kind === 'error' ? 'error-overlay' : 'success-overlay'}
    onclick={(e) => { if (e.target === e.currentTarget) clearMessage(); }}
  >
    <div class={kind === 'error' ? 'error-overlay-content' : 'success-overlay-content'}>
      <button
        class={kind === 'error' ? 'error-overlay-close' : 'success-overlay-close'}
        onclick={clearMessage}
        aria-label="Dismiss message"
      >&times;</button>
      <p><strong>{kind === 'error' ? 'Error:' : ''}</strong> {$overlayMessage.text}{#if $overlayMessage.link}
          <a href={$overlayMessage.link.href} onclick={clearMessage}>{$overlayMessage.link.label}</a>{/if}</p>
    </div>
  </div>
{/if}
