<script>
  let { data = {}, canManage = false, onUpdate = () => {} } = $props();
</script>

<div class="approved-header">
  <span class="col-indicator"></span>
  <strong>Approved</strong>
  <span class="count">{data.jobs?.length || 0}</span>
</div>
<div class="approved-body">
  <p>Approved area — {data.jobs?.length || 0} jobs, {data.unassigned?.length || 0} unassigned tasks</p>
</div>

<style>
  .approved-header { padding: 14px 16px 10px; display: flex; align-items: center; gap: 10px; border-bottom: 3px solid #4ade80; flex-shrink: 0; }
  .col-indicator { width: 4px; height: 24px; border-radius: 2px; background: #4ade80; }
  .count { font-size: 12px; color: #999; margin-left: auto; }
  .approved-body { flex: 1; padding: 12px; background: #f0faf3; overflow-y: auto; }
</style>
