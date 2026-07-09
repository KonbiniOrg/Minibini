<script>
  // The job nav rail: a skinny full-bleed strip welded under the JobHeader on
  // every job page, including the overview. Eight always-valid, job-scoped
  // section links — no server-computed document targets, no dimmed/inert
  // states. Every section is a static route (`/jobs/:id[/section]`); each
  // page decides internally what to show when the underlying document
  // doesn't exist yet. Overview sits first among the sections, set apart
  // with extra right margin rather than living outside them as a separate
  // "‹ Overview" back-link.
  const { job, current = null } = $props();

  let sections = $derived([
    { key: 'overview',  label: 'Overview',  href: `#/jobs/${job.job_id}` },
    { key: 'estimate',  label: 'Estimates', href: `#/jobs/${job.job_id}/estimate` },
    { key: 'tasks',     label: 'Tasks',     href: `#/jobs/${job.job_id}/tasks` },
    { key: 'invoice',   label: 'Invoices',  href: `#/jobs/${job.job_id}/invoice` },
    { key: 'shipments', label: 'Shipments', href: `#/jobs/${job.job_id}/shipments` },
    { key: 'pos',       label: 'POs',       href: `#/jobs/${job.job_id}/pos` },
    { key: 'emails',    label: 'Emails',    href: `#/jobs/${job.job_id}/emails`, seam: true },
    { key: 'history',   label: 'History',   href: `#/jobs/${job.job_id}/history` },
  ]);
</script>

<nav class="job-nav-rail" aria-label="Job sections">
  <div class="rail-sections">
    {#each sections as s (s.key)}
      {#if s.seam}<span class="rail-seam" aria-hidden="true"></span>{/if}
      <a
        class="rail-link"
        class:overview={s.key === 'overview'}
        class:active={current === s.key}
        href={s.href}
      >{s.label}</a>
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
    padding: 0 24px;
    box-sizing: border-box;
    flex: 0 0 auto;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }
  .job-nav-rail a { text-decoration: none; }
  /* The sections spread across the full width. */
  .rail-sections {
    flex: 1;
    display: flex;
    align-items: stretch;
    justify-content: space-evenly;
  }
  .rail-link {
    display: inline-flex;
    align-items: center;
    color: rgba(31, 41, 55, 0.65);
    border-bottom: 2px solid transparent;
  }
  .rail-link:hover { color: #1f2937; }
  .rail-link.active { color: #1f2937; border-bottom-color: #1f2937; }
  /* Overview is first among the sections but set apart: it's "up a level",
     not a sibling document category. */
  .rail-link.overview { margin-right: 32px; }
  /* Hairline divider ahead of Emails — the paper-trail seam. It's its own
     flex item so space-evenly centres it in the POS↔Emails gap, and so the
     Emails link keeps its natural width (its underline sits under the letters,
     not stretched across a padding gap). */
  .rail-seam {
    align-self: center;
    width: 1px;
    height: 14px;
    background: #d1d5db;
  }
</style>
