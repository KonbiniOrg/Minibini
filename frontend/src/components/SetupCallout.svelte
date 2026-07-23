<script>
  // Floating setup hint: a box with a pointer aimed at the greyed sidebar
  // entry it annotates. Purely presentational; parent controls visibility.
  let { message } = $props();
</script>

<div class="setup-callout" role="tooltip">
  <div class="pointer"></div>
  {message}
</div>

<style>
  .setup-callout {
    position: absolute;
    left: calc(100% + 12px);
    top: 50%;
    transform: translateY(-50%);
    width: 240px;
    background: #1f2937;
    color: #f9fafb;
    padding: 10px 12px;
    border-radius: 6px;
    font-size: 0.85rem;
    line-height: 1.35;
    box-shadow: 0 4px 14px rgba(0,0,0,0.25);
    z-index: 50;
  }
  .pointer {
    position: absolute;
    right: 100%;
    top: 50%;
    transform: translateY(-50%);
    border: 8px solid transparent;
    border-right-color: #1f2937;
  }
</style>
