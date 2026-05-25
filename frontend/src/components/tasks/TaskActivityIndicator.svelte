<script>
  import { taskActivity } from '../../lib/taskActivity.js';

  // Consistent "is this being worked right now?" marker. Pass a task carrying
  // has_active_blep / active_worker_count / has_bleps. `compact` drops the label
  // to just the dot (for dense layouts like the board card).
  let { task, compact = false } = $props();

  const activity = $derived(taskActivity(task));
</script>

{#if activity}
  <span class="ta ta-{activity.key}" style={`--ta-color:${activity.color}`} title={activity.label}>
    <span class="ta-dot" class:pulse={activity.pulse}></span>
    {#if !compact}<span class="ta-label">{activity.label}</span>{/if}
  </span>
{/if}

<style>
  .ta {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 600;
    color: var(--ta-color);
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }
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
