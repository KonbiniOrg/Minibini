<script>
  // SummaryBlock — the one dumb renderer for every job-overview lifecycle
  // block. It draws `model` (a Task 4 lib block result: scopeBlock,
  // workBlock, materialsBlock, spendBlock, invoicingBlock, deliveryBlock) —
  // no fetching, no business rules, no anchors. See frontend/src/lib/jobOverview.js
  // for the return shape and frontend/src/css/app.css (grep "summary-block")
  // for the CSS vocabulary this renders into.
  // `accent` names the block's identity color (accent-<name> class in
  // app.css) — the active card's left edge + softened 1px ring. Optional;
  // without it the vocabulary's default blue applies.
  const { title, model, accent = null } = $props();
  const accentClass = $derived(accent ? `accent-${accent}` : '');

  // Only bad/warn/good carry a color class (app.css has no .clock-neutral —
  // neutral tones render in the vocabulary's default ink).
  function toneClass(tone) {
    return tone === 'bad' || tone === 'warn' || tone === 'good' ? `clock-${tone}` : '';
  }
</script>

{#if model.state === 'active'}
  <div class="summary-block active {accentClass}">
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
  </div>
{:else if model.state === 'frozen'}
  <div class="summary-block frozen {accentClass}">
    <span class="summary-block-title">{title}</span>
    <span>{model.frozenText}</span>
  </div>
{:else}
  <div class="summary-block dormant {accentClass}">
    <span class="summary-block-title">{title}</span>
    <span>{model.dormantText}</span>
  </div>
{/if}
