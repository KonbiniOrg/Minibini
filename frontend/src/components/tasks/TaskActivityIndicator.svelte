<script>
  import { taskActivity } from '../../lib/taskActivity.js';

  // Consistent "is this being worked right now?" marker. Pass a task carrying
  // has_active_blep / active_worker_count / has_bleps. `compact` drops the label
  // to just the dot (for dense layouts like the board card). `pill` wraps the
  // indicator in the shared .status-badge pill (title-row contexts); colors come
  // from the global status-{activity key} classes so pills match app-wide.
  let { task, compact = false, pill = false } = $props();

  const activity = $derived(taskActivity(task));
</script>

{#if activity}
  <span
    class={pill
      ? `ta ta-${activity.key} pill status-badge status-${activity.key}`
      : `ta ta-${activity.key}`}
    style={`--ta-color:${activity.color}`}
    title={activity.label}
  >
    <span class="ta-dot" class:pulse={activity.pulse}></span>
    {#if !compact}<span class="ta-label">{activity.label}</span>{/if}
  </span>
{/if}

<style>
  .ta {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-weight: 600;
  }
  /* Non-pill: the classic small colored label. Pill mode leaves typography and
     text color to the global .status-badge / .status-{key} classes. */
  .ta:not(.pill) {
    font-size: 11px;
    color: var(--ta-color);
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }
  .ta.pill { gap: 6px; }
  .ta-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ta-color);
    flex-shrink: 0;
  }
  .ta-dot.pulse {
    box-shadow: 0 0 0 0 var(--ta-color);
    animation: ta-pulse 1.4s ease-out infinite;
  }
  @keyframes ta-pulse {
    0%   { box-shadow: 0 0 0 0 color-mix(in srgb, var(--ta-color) 55%, transparent); }
    70%  { box-shadow: 0 0 0 6px color-mix(in srgb, var(--ta-color) 0%, transparent); }
    100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--ta-color) 0%, transparent); }
  }
</style>
