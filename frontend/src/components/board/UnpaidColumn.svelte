<script>
  import UnpaidCard from './UnpaidCard.svelte';
  import NewJobButton from './NewJobButton.svelte';
  import { UNPAID_SECTIONS, unpaidSectionKey } from '../../lib/unpaidSections.js';
  let { jobs = [] } = $props();

  // Column order, top to bottom: Needs Invoice / Invoice Drafted / Awaiting
  // Payment. Header colors match the card tab (UnpaidCard reads the same
  // bucket), so a header reads as the tab of the cards beneath it.
  let sections = $derived(
    UNPAID_SECTIONS
      .map(s => ({ ...s, jobs: jobs.filter(j => unpaidSectionKey(j) === s.key) }))
      .filter(s => s.jobs.length > 0)
  );
</script>

<div class="column-header">
  <strong>Unpaid</strong>
  <span class="count">{jobs.length}</span>
  <NewJobButton />
</div>
<div class="column-body">
  {#each sections as section (section.key)}
    <div class="section-divider" style="--section-color: {section.color};">
      <span class="section-label">{section.label}</span>
    </div>
    {#each section.jobs as job (job.job_id)}
      <a href="#/jobs/{job.job_id}" class="card-link">
        <UnpaidCard {job} />
      </a>
    {/each}
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No unpaid jobs</p>
  {/if}
</div>

<style>
  .column-header { position: relative; padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #f59e0b; flex-shrink: 0; }
  .count { font-size: 12px; color: #999; }
  .column-body {
    flex: 1; overflow-y: auto; padding: 12px; background: #f5eddb;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 10px;
    align-content: start;
  }
  .card-link { text-decoration: none; color: inherit; display: block; }
  .section-divider {
    grid-column: 1 / -1;
    display: flex; align-items: center; gap: 8px; margin: 8px 0 6px;
  }
  .section-divider::before,
  .section-divider::after { content: ''; flex: 1; height: 1px; background: var(--section-color); opacity: 0.4; }
  .section-label { font-size: 10px; font-weight: 700; color: var(--section-color); letter-spacing: 0.5px; text-transform: uppercase; white-space: nowrap; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
