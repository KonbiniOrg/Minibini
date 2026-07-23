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
    width: 340px;
    background: #b45309;
    color: #fffbeb;
    border: 2px solid #f59e0b;
    padding: 16px 18px;
    border-radius: 10px;
    font-size: 1.05rem;
    font-weight: 500;
    line-height: 1.45;
    box-shadow: 0 6px 22px rgba(0,0,0,0.35);
    z-index: 50;
  }
  .pointer {
    position: absolute;
    right: 100%;
    top: 50%;
    transform: translateY(-50%);
    border: 14px solid transparent;
    border-right-color: #f59e0b;
  }
</style>
