<script>
  // TabHeader — the head of one job tab (frontend/README.md → "Job tab
  // structure"). The tab body is a <section aria-labelledby={id}>; this is
  // its first child:
  //
  //   <section class="page-body" aria-labelledby="tab-tasks">
  //     <TabHeader id="tab-tasks" title="Tasks" {actions} />
  //     …key numbers, <section><h3>…</h3></section>s, EmptyState…
  //   </section>
  //
  // Title (the tab's one <h2>) and optional badges on the left; actions as a
  // trailing group on the right. Mirrors the shadcn plan's PageHeader
  // template (title / badges / actions) so it can be swapped later.
  // `class` adds classes to the <header>: the document tabs pass "toolbar"
  // to keep the shared .toolbar button look (app.css) their actions had.
  let {
    id,
    title,
    // Dim the title (a superseded document).
    muted = false,
    // Keep the h2 for screen readers and the heading order, but don't show it:
    // on tabs whose title only repeats the rail tab, the tab is the title.
    titleHidden = false,
    class: className = '',
    badges = null,
    actions = null,
  } = $props();
</script>

<header class="tab-header {className}" class:bare={titleHidden && !badges && !actions}>
  <h2 {id} class="tab-title" class:muted class:visually-hidden={titleHidden}>{title}</h2>
  {#if badges}<div class="tab-header-badges">{@render badges()}</div>{/if}
  {#if actions}<div class="tab-header-actions">{@render actions()}</div>{/if}
</header>

<style>
  .tab-header {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    padding: 8px 0;
  }
  /* Same size/weight the document tabs' title (.page-title) always had;
     every tab's h2 now reads alike. */
  .tab-title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: var(--text-fg);
  }
  .tab-title.muted { opacity: 0.6; }
  /* Off screen, still read by screen readers and counted in the outline. */
  .tab-title.visually-hidden {
    position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
    overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
  }
  /* Hidden title and nothing else: the header takes no space. */
  .tab-header.bare { padding: 0; }
  .tab-header-badges,
  .tab-header-actions {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  }
  .tab-header-actions { margin-left: auto; }
</style>
