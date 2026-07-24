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
    left: calc(100% + 18px);
    top: 50%;
    transform: translateY(-50%);
    width: 420px;
    background: #b45309;
    color: #fffbeb;
    border: 3px solid #f59e0b;
    padding: 20px 22px;
    border-radius: 12px;
    font-size: 1.15rem;
    font-weight: 500;
    line-height: 1.5;
    white-space: normal;      /* undo the nav's nowrap so text wraps */
    overflow-wrap: break-word;
    box-shadow: 0 8px 26px rgba(0,0,0,0.4);
    z-index: 50;
  }
  .pointer {
    position: absolute;
    right: 100%;
    top: 50%;
    transform: translateY(-50%);
    border: 18px solid transparent;
    border-right-color: #f59e0b;
  }
</style>
