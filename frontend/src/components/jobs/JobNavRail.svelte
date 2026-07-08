<script>
  // The job nav rail: a skinny full-bleed strip welded under the JobHeader on
  // every job page EXCEPT the overview (which hosts these sections itself).
  // "‹ Overview" goes up a level; the section links jump to each category's
  // most recent live document (ids from job.nav_targets, computed server-side
  // on the job detail payload) or the job-scoped page for tasks/shipments.
  // A category with no document yet renders dimmed and inert — the rail is
  // identical on every page so it reads as chrome, not content.
  const { job, current = null } = $props();

  let targets = $derived(job?.nav_targets ?? {});
  let sections = $derived([
    { key: 'estimate', label: 'Estimate', href: targets.estimate != null ? `#/estimates/${targets.estimate}` : null },
    { key: 'tasks', label: 'Tasks', href: `#/jobs/${job.job_id}/tasklist` },
    { key: 'invoice', label: 'Invoice', href: targets.invoice != null ? `#/invoices/${targets.invoice}` : null },
    { key: 'shipments', label: 'Shipments', href: `#/jobs/${job.job_id}/shipments` },
    { key: 'pos', label: 'POs', href: targets.po != null ? `#/purchase-orders/${targets.po}` : null },
  ]);
</script>

<nav class="job-nav-rail" aria-label="Job sections">
  <a class="rail-overview" href="#/jobs/{job.job_id}">‹ Overview</a>
  <div class="rail-sections">
    {#each sections as s (s.key)}
      {#if s.href}
        <a class="rail-link" class:active={current === s.key} href={s.href}>{s.label}</a>
      {:else}
        <span class="rail-link empty" title="Nothing here yet">{s.label}</span>
      {/if}
    {/each}
  </div>
</nav>

<style>
  /* A light strip under the dark JobHeader, framed by medium-shade borders
     so it reads as the banner's baseboard rather than page content.
     Deliberately skinny — one line of micro-caps, no boxes. */
  .job-nav-rail {
    background: #f9fafb;
    color: #1f2937;
    height: 28px;
    display: flex;
    align-items: stretch;
    border-top: 2px solid #9ca3af;
    border-bottom: 2px solid #9ca3af;
    padding: 0 24px 0 76px; /* text aligns with the header's title block */
    box-sizing: border-box;
    flex: 0 0 auto;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }
  .job-nav-rail a { text-decoration: none; }
  .rail-overview,
  .rail-link {
    display: inline-flex;
    align-items: center;
    color: rgba(31, 41, 55, 0.65);
    border-bottom: 2px solid transparent;
  }
  .rail-overview {
    margin-right: 48px; /* set apart: "up a level", not a sibling section */
    letter-spacing: 0.4px;
  }
  /* The sections spread across the full remaining width. */
  .rail-sections {
    flex: 1;
    display: flex;
    align-items: stretch;
    justify-content: space-evenly;
  }
  .rail-overview:hover,
  a.rail-link:hover { color: #1f2937; }
  .rail-link.active { color: #1f2937; border-bottom-color: #1f2937; }
  .rail-link.empty { color: rgba(31, 41, 55, 0.28); cursor: default; }
</style>
