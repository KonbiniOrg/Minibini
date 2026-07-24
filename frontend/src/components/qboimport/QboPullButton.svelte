<script>
  // Permanently-visible pull affordance for an area (shown even while the
  // area's panel is dismissed — pulling here reopens ONLY this area).
  import { qboImportApi, formatPullTime } from '../../lib/qboImport.js';
  import { errorMessage } from '../../lib/api.js';
  import { setupStatus, refreshSetupStatus } from '../../stores/setupStatus.js';

  let { area, onPulled = () => {} } = $props();
  let busy = $state(false);
  let message = $state('');

  async function pull() {
    busy = true; message = '';
    try {
      await qboImportApi.pull(area);
      refreshSetupStatus();
      onPulled();
    } catch (e) {
      message = errorMessage(e);
    } finally {
      busy = false;
    }
  }
</script>

<p class="qbo-pull">
  <button type="button" onclick={pull} disabled={busy}>
    {busy ? 'Pulling…' : 'Pull from QuickBooks'}
  </button>
  <small>last pull: {formatPullTime($setupStatus.last_pull_at)}</small>
  {#if message}<em class="err">{message}</em>{/if}
</p>

<style>
  .qbo-pull small { color: #6b7280; margin-left: 8px; }
  .err { color: #b91c1c; margin-left: 8px; }
</style>
