<script>
  import { onMount } from 'svelte';
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
  let navVisible = $state(false);

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

  // Hide app-level nav and footer when board is active
  onMount(() => {
    const header = document.querySelector('.site-header-placeholder');
    const footer = document.querySelector('footer');
    const hr = document.querySelector('hr');
    if (header) header.style.display = 'none';
    if (footer) footer.style.display = 'none';
    if (hr) hr.style.display = 'none';

    return () => {
      if (header) header.style.display = '';
      if (footer) footer.style.display = '';
      if (hr) hr.style.display = '';
    };
  });

  function handleMouseMove(e) {
    navVisible = e.clientY <= 5;
  }
</script>

<svelte:window onmousemove={handleMouseMove} />

<div class="board-page">
  <div class="slide-nav" class:visible={navVisible}>
    <nav class="board-nav">
      <a href="#/">HOME</a>
      <span class="sep">◆</span>
      <a href="#/contacts">CONTACTS</a>
      <span class="sep">◆</span>
      <a href="#/businesses">BUSINESSES</a>
      <span class="sep">◆</span>
      <a href="#/jobs">JOBS</a>
      <span class="sep">◆</span>
      <a href="#/settings">SETTINGS</a>
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
</div>

<style>
  .board-page {
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .slide-nav {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 200;
    transform: translateY(-100%);
    transition: transform 0.2s ease;
    background: #fff;
    border-bottom: 1px solid #ddd;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  }
  .slide-nav.visible {
    transform: translateY(0);
  }

  .board-nav {
    padding: 8px 16px;
    text-align: center;
    font-size: 13px;
  }
  .board-nav a {
    text-decoration: none;
    color: #333;
    padding: 4px 8px;
  }
  .board-nav a:hover { color: #2563eb; }
  .sep { color: #ccc; font-size: 10px; }

  .board {
    display: flex;
    flex: 1;
    overflow: hidden;
  }
  .board-col { display: flex; flex-direction: column; overflow: hidden; }
  .board-col.pipeline { flex-shrink: 0; }
  .board-col.approved { flex: 1; }
  .board-col.closed { flex-shrink: 0; }
</style>
