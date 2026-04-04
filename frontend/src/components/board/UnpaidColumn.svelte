<script>
  let { jobs = [] } = $props();
</script>
<div>
  <div class="column-header"><strong>Unpaid</strong><span class="count">{jobs.length}</span></div>
  <p>Coming soon</p>
</div>
<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #f59e0b; }
  .count { font-size: 12px; color: #999; }
</style>
