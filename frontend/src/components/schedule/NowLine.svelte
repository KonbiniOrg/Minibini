<script>
  let { x } = $props();
</script>

{#if x !== null && x !== undefined}
  <div class="now-line" style="left: {x}px;"></div>
{/if}

<style>
  .now-line {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    background: #000;
    pointer-events: none;
    z-index: 2;
  }
  .now-line::before {
    content: 'now';
    position: absolute;
    top: -12px;
    left: -16px;
    font-size: 9px;
    color: #000;
    background: #fff;
    padding: 0 3px;
    line-height: 1.2;
  }
</style>
