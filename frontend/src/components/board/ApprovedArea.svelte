<script>
  import JobChipStrip from './JobChipStrip.svelte';
  import WorkerColumns from './WorkerColumns.svelte';
  import UnassignedPool from './UnassignedPool.svelte';

  let { data = {}, canManage = false, onUpdate = () => {} } = $props();
  let focusedJobId = $state(null);
</script>

<div class="approved-header">
  <span class="col-indicator"></span>
  <strong>Approved</strong>
  <span class="count">{data.jobs?.length || 0}</span>
</div>
<div class="approved-content">
  <JobChipStrip jobs={data.jobs || []} bind:focusedJobId />

  <div class="worker-area">
    <div class="worker-section">
      <WorkerColumns
        workers={data.workers || []}
        availableWorkers={data.available_workers || []}
        {canManage}
        {focusedJobId}
        {onUpdate}
      />
    </div>
    <div class="h-resize"></div>
    <div class="unassigned-section">
      <UnassignedPool
        tasks={data.unassigned || []}
        {canManage}
        {focusedJobId}
        {onUpdate}
      />
    </div>
  </div>
</div>

<style>
  .approved-header { padding: 14px 16px 10px; display: flex; align-items: center; gap: 10px; border-bottom: 3px solid #4ade80; flex-shrink: 0; }
  .col-indicator { width: 4px; height: 24px; border-radius: 2px; background: #4ade80; }
  .count { font-size: 12px; color: #999; margin-left: auto; }
  .approved-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .worker-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
  .worker-section { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .h-resize { height: 5px; cursor: row-resize; background: #e0e0e0; flex-shrink: 0; }
  .h-resize:hover { background: #4ade80; }
  .unassigned-section { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
</style>
