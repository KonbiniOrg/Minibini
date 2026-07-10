<script>
  import { api } from '../../lib/api.js';
  import { getJobWs, rememberBand } from '../../stores/jobWorkspace.js';
  import DeliverablesSection from './DeliverablesSection.svelte';
  import EmailPanel from '../EmailPanel.svelte';

  let { job } = $props();
  let expanded = $state(getJobWs(job.job_id).band === 'expanded');
  let emails = $state(null);

  // Collapsed band fetches NOTHING (design review note 2). Load on expand.
  $effect(() => {
    if (expanded && emails === null && job?.job_id) {
      api.get(`/api/emails/?job=${job.job_id}`)
        .then((r) => { emails = r; })
        .catch(() => { emails = { results: [] }; });
    }
  });

  function toggle() {
    expanded = !expanded;
    rememberBand(job.job_id, expanded ? 'expanded' : 'collapsed');
  }
</script>

<div class="context-band" class:collapsed={!expanded}>
  <button type="button" class="context-band-toggle" onclick={toggle}
          aria-expanded={expanded}>
    {expanded ? '▾ Hide job context' : '▸ Job context'}
  </button>
  {#if expanded}
    <div class="context-band-grid">
      <div class="panel">
        <div class="panel-head">Description</div>
        <div class="panel-scroll preserve-breaks">{job.description || '—'}</div>
      </div>
      <DeliverablesSection jobId={job.job_id} canManage={job.can_manage} />
      <div class="panel">
        <div class="panel-head">Email</div>
        <EmailPanel {emails} showHeading={false} />
      </div>
    </div>
  {/if}
</div>
