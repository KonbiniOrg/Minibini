<script>
  // SummaryBlock — the one dumb renderer for every job-overview lifecycle
  // block. It draws `model` (a Task 4 lib block result: scopeBlock,
  // workBlock, materialsBlock, spendBlock, invoicingBlock, deliveryBlock) —
  // no fetching, no business rules. See frontend/src/lib/jobOverview.js
  // for the return shape and frontend/src/css/app.css (grep "summary-block")
  // for the CSS vocabulary this renders into.
  // `accent` names the block's identity color (accent-<name> class in
  // app.css) — the active card's left edge + softened 1px ring. Optional;
  // without it the vocabulary's default blue applies.
  //
  // The card IS the link (2026-07-28, reversing the 2026-07-09 "no block-level
  // links" decision — see jobs-and-tasks.md §9.1a). `model.href` is decided in
  // jobOverview.js; this component never picks a target. A plain <a> wrapping
  // the card is valid only because the card renders NO interactive
  // descendants — adding a button or link inside would invalidate the markup
  // and force the stretched-link overlay pattern instead.
  const { title, model, accent = null } = $props();
  const accentClass = $derived(accent ? `accent-${accent}` : '');

  // Only bad/warn/good carry a color class (app.css has no .clock-neutral —
  // neutral tones render in the vocabulary's default ink).
  function toneClass(tone) {
    return tone === 'bad' || tone === 'warn' || tone === 'good' ? `clock-${tone}` : '';
  }
</script>

{#if model.state === 'active'}
  <a class="summary-block active {accentClass}" href={model.href}>
    <div class="summary-block-title">{title}</div>
    <div class="stat-spread">
      {#each model.stats as stat}
        <div class="stat">
          <div class="stat-label">{stat.label}</div>
          <div class="stat-value {toneClass(stat.valueTone)}">
            {stat.value}{#if stat.unit}<span class="unit">{stat.unit}</span>{/if}
            {#if stat.pill}<span class="status-badge status-{stat.pill.tone}">{stat.pill.text}</span>{/if}
          </div>
          {#if stat.sub}
            <div class="stat-sub {toneClass(stat.subTone)}">{stat.sub}</div>
          {/if}
          {#if stat.bar != null}
            <div class="stat-progress"><div class="stat-progress-fill" style="width: {stat.bar}%"></div></div>
          {/if}
        </div>
      {/each}
    </div>
    {#if model.clock}
      <div class="clock-line {toneClass(model.clock.tone)}">
        {#each model.clock.lines as line}
          <div>{line}</div>
        {/each}
      </div>
    {/if}
  </a>
{:else if model.state === 'frozen'}
  <a class="summary-block frozen {accentClass}" href={model.href}>
    <span class="summary-block-title">{title}</span>
    <span>{model.frozenText}</span>
  </a>
{:else}
  <a class="summary-block dormant {accentClass}" href={model.href}>
    <span class="summary-block-title">{title}</span>
    <span>{model.dormantText}</span>
  </a>
{/if}
