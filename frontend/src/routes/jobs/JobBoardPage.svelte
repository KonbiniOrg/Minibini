<script>
  import { api } from '../../lib/api.js';
  import { user } from '../../stores/auth.js';
  import PipelineColumn from '../../components/board/PipelineColumn.svelte';
  import ApprovedArea from '../../components/board/ApprovedArea.svelte';
  import ClosedColumn from '../../components/board/ClosedColumn.svelte';
  import ResizeHandle from '../../components/board/ResizeHandle.svelte';

  let boardData = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let pipelineWidth = $state(270);
  let closedWidth = $state(270);

  async function loadBoard() {
    loading = true;
    error = null;
    try {
      boardData = await api.get('/api/jobs/board/');
    } catch (e) {
      error = e.message || 'Failed to load board';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    loadBoard();
  });

  function canManageJobs() {
    return $user?.permissions?.includes('can_manage_jobs');
  }
</script>

<div class="board-header">
  <h1>Job Board</h1>
  <nav class="view-toggle">
    <a href="#/jobs/board" class="active">Board</a>
    <a href="#/jobs">List</a>
  </nav>
</div>

{#if loading}
  <p>Loading board...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if boardData}
  <div class="board">
    <div class="board-col pipeline" style="width: {pipelineWidth}px;">
      <PipelineColumn jobs={boardData.pipeline} />
    </div>
    <ResizeHandle direction="vertical" onResize={(delta) => { pipelineWidth = Math.max(200, pipelineWidth + delta); }} />
    <div class="board-col approved">
      <ApprovedArea data={boardData.approved} canManage={canManageJobs()} onUpdate={loadBoard} />
    </div>
    <ResizeHandle direction="vertical" onResize={(delta) => { closedWidth = Math.max(200, closedWidth - delta); }} />
    <div class="board-col closed" style="width: {closedWidth}px;">
      <ClosedColumn jobs={boardData.closed} />
    </div>
  </div>
{/if}

<style>
  .board-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 24px;
    border-bottom: 1px solid #e0e0e0;
  }
  .board-header h1 { font-size: 20px; margin: 0; }
  .view-toggle { display: flex; gap: 4px; background: #f0f0f0; border-radius: 6px; padding: 3px; }
  .view-toggle a {
    padding: 5px 14px; border-radius: 4px; font-size: 13px;
    text-decoration: none; color: #888;
  }
  .view-toggle a.active { background: #fff; color: #1a1a1a; box-shadow: 0 1px 2px rgba(0,0,0,0.08); }

  .board {
    display: flex;
    height: calc(100vh - 110px);
    overflow: hidden;
  }
  .board-col { display: flex; flex-direction: column; overflow: hidden; }
  .board-col.pipeline { flex-shrink: 0; }
  .board-col.approved { flex: 1; }
  .board-col.closed { flex-shrink: 0; }
</style>
