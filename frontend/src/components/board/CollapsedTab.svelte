<script>
  let { label, count = null, theme = 'gray', onclick = () => {} } = $props();

  const THEMES = {
    pipeline: { bg: '#e8efff', border: '#60a5fa', text: '#3b82f6' },
    approved: { bg: '#e5f8ec', border: '#4ade80', text: '#16a34a' },
    unpaid:   { bg: '#fef4e5', border: '#f59e0b', text: '#d97706' },
    closed:   { bg: '#f0f0f1', border: '#9ca3af', text: '#6b7280' },
    gray:     { bg: '#f0f0f1', border: '#9ca3af', text: '#6b7280' },
  };

  let colors = $derived(THEMES[theme] || THEMES.gray);
</script>

<div
  class="col-tab"
  style="background:{colors.bg}; border-right: 3px solid {colors.border};"
  {onclick}
  role="button"
  tabindex="0"
  onkeydown={(e) => { if (e.key === 'Enter') onclick(); }}
>
  <span class="tab-label" style="color:{colors.text};">{label}</span>
  {#if count !== null}
    <span class="tab-count">{count}</span>
  {/if}
</div>

<style>
  .col-tab {
    width: 32px; flex-shrink: 0; cursor: pointer; position: relative;
    display: flex; flex-direction: column; align-items: center;
    padding-top: 14px; gap: 8px;
    transition: filter 0.15s;
  }
  .col-tab:hover { filter: brightness(0.95); }
  .tab-label {
    writing-mode: vertical-rl; text-orientation: mixed;
    transform: rotate(180deg);
    font-size: 12px; font-weight: 600; letter-spacing: 0.5px;
    white-space: nowrap; user-select: none;
  }
  .tab-count {
    font-size: 10px; color: #999; writing-mode: horizontal-tb;
  }
</style>
