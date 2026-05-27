<script>
  import { untrack } from 'svelte';
  import { api } from '../../lib/api.js';
  import { user } from '../../stores/auth.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';
  import CollapsedTab from '../../components/board/CollapsedTab.svelte';
  import PipelineColumn from '../../components/board/PipelineColumn.svelte';
  import ApprovedArea from '../../components/board/ApprovedArea.svelte';
  import UnpaidColumn from '../../components/board/UnpaidColumn.svelte';
  import ClosedColumn from '../../components/board/ClosedColumn.svelte';

  const VALID_COLS = ['pipeline', 'approved', 'unpaid', 'closed'];
  let activeCol = $state(VALID_COLS.includes(sessionStorage.getItem('boardActiveCol')) ? sessionStorage.getItem('boardActiveCol') : 'approved');

  let pipelineData = $state(null);
  let approvedData = $state(null);
  let unpaidData = $state(null);
  let closedData = $state(null);

  let pipelineLoading = $state(false);
  let approvedLoading = $state(false);
  let unpaidLoading = $state(false);
  let closedLoading = $state(false);

  let pipelineCount = $state(null);
  let unpaidCount = $state(null);

  async function loadColumn(col) {
    const endpoints = {
      pipeline: '/api/jobs/board/pipeline/',
      approved: '/api/jobs/board/approved/',
      unpaid: '/api/jobs/board/unpaid/',
      closed: '/api/jobs/board/closed/',
    };
    const setLoading = { pipeline: v => pipelineLoading = v, approved: v => approvedLoading = v, unpaid: v => unpaidLoading = v, closed: v => closedLoading = v };
    const setData = {
      pipeline: d => { pipelineData = d; pipelineCount = d.jobs?.length ?? null; },
      approved: d => { approvedData = d; },
      unpaid: d => { unpaidData = d; unpaidCount = d.jobs?.length ?? null; },
      closed: d => { closedData = d; },
    };

    setLoading[col](true);
    try {
      const data = await api.get(endpoints[col]);
      setData[col](data);
    } catch (e) {
      console.error(`Failed to load ${col}:`, e);
    } finally {
      setLoading[col](false);
    }
  }

  function openCol(col) {
    activeCol = col;
    sessionStorage.setItem('boardActiveCol', col);
    loadColumn(col);
  }

  function canManageJobs() {
    return $user?.permissions?.includes('can_manage_jobs');
  }

  $effect(() => {
    loadColumn(activeCol);
  });

  // Reload the active column when a blep changes (live/paused markers update).
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      untrack(() => loadColumn(activeCol));
    }
  });
</script>

<div class="board-page">
  <div class="board">
    {#if activeCol === 'pipeline'}
      <div class="col-expanded">
        {#if pipelineLoading}
          <p class="loading">Loading pipeline...</p>
        {:else if pipelineData}
          <PipelineColumn jobs={pipelineData.jobs} />
        {/if}
      </div>
    {:else}
      <CollapsedTab label="Pipeline" count={pipelineCount} theme="pipeline" onclick={() => openCol('pipeline')} />
    {/if}

    {#if activeCol === 'approved'}
      <div class="col-expanded">
        {#if approvedLoading}
          <p class="loading">Loading...</p>
        {:else if approvedData}
          <ApprovedArea data={approvedData} canManage={canManageJobs()} onUpdate={() => loadColumn('approved')} />
        {/if}
      </div>
    {:else}
      <CollapsedTab label="In Progress" count={approvedData?.jobs?.length ?? null} theme="approved" onclick={() => openCol('approved')} />
    {/if}

    {#if activeCol === 'unpaid'}
      <div class="col-expanded">
        {#if unpaidLoading}
          <p class="loading">Loading unpaid...</p>
        {:else if unpaidData}
          <UnpaidColumn jobs={unpaidData.jobs} />
        {/if}
      </div>
    {:else}
      <CollapsedTab label="Unpaid" count={unpaidCount} theme="unpaid" onclick={() => openCol('unpaid')} />
    {/if}

    {#if activeCol === 'closed'}
      <div class="col-expanded">
        {#if closedLoading}
          <p class="loading">Loading closed...</p>
        {:else if closedData}
          <ClosedColumn jobs={closedData.jobs} />
        {/if}
      </div>
    {:else}
      <CollapsedTab label="Closed" theme="closed" onclick={() => openCol('closed')} />
    {/if}
  </div>
</div>

<style>
  .board-page {
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .board {
    display: flex;
    flex: 1;
    overflow: hidden;
  }
  .col-expanded {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: expand 0.18s ease-in-out;
  }
  @keyframes expand {
    from { opacity: 0.5; }
    to { opacity: 1; }
  }
  .loading {
    padding: 20px;
    text-align: center;
    color: #999;
  }
</style>
