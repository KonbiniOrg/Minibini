<script>
  // The board's New Job entry point, one per pillar header (the board is the
  // sidebar's "Jobs" destination, and only one pillar is expanded at a time,
  // so exactly one of these is on screen). Absolutely positioned so it sits
  // top-right without pushing the header's centered title off-center — the
  // host header only has to be `position: relative`.
  //
  // It navigates, so it's an <a> dressed as a button (UI Decisions: links
  // navigate, buttons act). RM 2026-07-31: the create flow itself becomes a
  // Modal later; this is just the way in.
  import { canManageJobs } from '../../stores/permissions.js';
</script>

{#if $canManageJobs}
  <a class="new-job" href="#/jobs/new">New Job</a>
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
    text-decoration: none;
    font-size: 12px;
    font-family: inherit;
    white-space: nowrap;
  }
  .new-job:hover {
    background: #f3f4f6;
  }
</style>
