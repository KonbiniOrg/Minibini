<script>
  // The board's New Job entry point, one per pillar header (the board is the
  // sidebar's "Jobs" destination, and only one pillar is expanded at a time,
  // so exactly one of these is on screen). Absolutely positioned so it sits
  // top-right without pushing the header's centered title off-center — the
  // host header only has to be `position: relative`.
  //
  // It opens JobCreateModal in place (buttons act) — 2026-10-10, the create
  // form became a modal as RM anticipated on 2026-07-31.
  import { canManageJobs } from '../../stores/permissions.js';
  import JobCreateModal from '../jobs/JobCreateModal.svelte';

  let open = $state(false);
</script>

{#if $canManageJobs}
  <button type="button" class="new-job" onclick={() => { open = true; }}>New Job</button>
  <JobCreateModal {open} onClose={() => { open = false; }} />
{/if}

<style>
  .new-job {
    position: absolute;
    right: 16px;
    top: 12px;
    padding: 3px 9px;
    border: 1px solid #d1d5db;
    border-radius: 3px;
    background: #fff;
    color: #2563eb;
    font-size: 12px;
    font-family: inherit;
    white-space: nowrap;
    cursor: pointer;
  }
  .new-job:hover {
    background: #f3f4f6;
  }
</style>
