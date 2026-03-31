<script>
  let { direction = 'vertical', onResize = () => {} } = $props();
  let active = $state(false);
  let startPos = 0;

  function handleMouseDown(e) {
    e.preventDefault();
    active = true;
    startPos = direction === 'vertical' ? e.clientX : e.clientY;

    function onMouseMove(e) {
      const currentPos = direction === 'vertical' ? e.clientX : e.clientY;
      onResize(currentPos - startPos);
      startPos = currentPos;
    }

    function onMouseUp() {
      active = false;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    }

    document.body.style.userSelect = 'none';
    document.body.style.cursor = direction === 'vertical' ? 'col-resize' : 'row-resize';
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }
</script>

<div
  class="resize-handle {direction}"
  class:active
  onmousedown={handleMouseDown}
  role="separator"
></div>

<style>
  .resize-handle { flex-shrink: 0; transition: background 0.15s; }
  .resize-handle.vertical { width: 5px; cursor: col-resize; background: #e0e0e0; }
  .resize-handle.horizontal { height: 5px; cursor: row-resize; background: #e0e0e0; }
  .resize-handle:hover, .resize-handle.active { background: #4ade80; }
</style>
