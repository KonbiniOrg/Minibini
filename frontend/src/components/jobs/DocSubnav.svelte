<script>
  import { tick } from 'svelte';

  // `section` is the JobNavRail section key this document set belongs to
  // ('estimate' | 'invoice' | …). The band draws a caret pinned under that
  // rail link and slides the document row so the current document sits under
  // the caret (clamped so nothing runs off the left). When the row is wider
  // than the band it wraps to further lines, pushing the page down.
  let { items = [], section = null } = $props();

  // Caret triangle height — keep in sync with the border-bottom width in the
  // `.doc-subnav-caret` rule so the caret's base lands on the rail underline.
  const CARET_H = 6;
  // Must match the `.doc-subnav-row` gap in app.css.
  const ROW_GAP = 14;

  let barEl;
  let caretX = $state(null);   // px from the band's left edge, or null (unmeasured)
  let caretY = $state(0);      // px from the band's top edge (negative: up into the rail)
  let rowPad = $state(0);      // left offset applied to the document row

  function measure() {
    if (!barEl) return;
    const barRect = barEl.getBoundingClientRect();
    if (!barRect.width) return;  // not laid out yet (e.g. jsdom) — leave caret hidden

    const railLink = section
      ? document.querySelector(`.job-nav-rail .rail-link[data-section="${section}"]`)
      : null;
    if (!railLink) { caretX = null; rowPad = 0; return; }

    const railRect = railLink.getBoundingClientRect();
    const cx = railRect.left + railRect.width / 2 - barRect.left;
    caretX = cx;
    // Raise the caret so its base sits on the rail link's underline (its bottom
    // edge) and it points up toward the label — it paints over the rail because
    // the band comes later in the DOM.
    caretY = railRect.bottom - barRect.top - CARET_H;

    const rowEl = barEl.querySelector('.doc-subnav-row');
    const chips = rowEl ? rowEl.querySelectorAll('.doc-subnav-link') : [];
    if (!chips.length) { rowPad = 0; return; }

    // Centre the whole document group under the caret — the same layout no
    // matter which document is being viewed. `getBoundingClientRect().left` on
    // the row is its border-box edge, unaffected by the padding-left we apply,
    // so leftInset stays stable; chip widths don't change with the active
    // marker (no bold), so the group width is stable too. Clamp to >= 0 so the
    // group never runs off the left; when it's wider than the band it stays
    // left-clamped and wraps (pushing the page down).
    const leftInset = rowEl.getBoundingClientRect().left - barRect.left;
    let groupW = 0;
    chips.forEach((c) => { groupW += c.getBoundingClientRect().width; });
    groupW += ROW_GAP * (chips.length - 1);
    rowPad = Math.max(0, cx - leftInset - groupW / 2);
  }

  // Re-measure whenever the document set or the target section changes.
  $effect(() => {
    items; section;
    tick().then(measure);
  });

  // Keep the caret aligned when the rail reflows (window resize).
  $effect(() => {
    const onResize = () => measure();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  });
</script>

<nav class="doc-subnav" aria-label="Documents" bind:this={barEl}>
  {#if caretX != null}
    <span class="doc-subnav-caret" style="left: {caretX}px; top: {caretY}px" aria-hidden="true"></span>
  {/if}
  <div class="doc-subnav-row" style="padding-left: {rowPad}px">
    {#each items as it (it.id)}
      <a href={it.href} class="doc-subnav-link" class:active={it.current}>
        {it.label}
        {#if it.status}<span class="status-badge doc-subnav-pill status-{it.status}">{it.status}</span>{/if}
      </a>
    {/each}
  </div>
</nav>
