<script>
  import '../css/accordion.css';

  let {
    title,
    meta = '',
    metaDim = '',
    open = false,
    headerBg = '#475569',
    borderColor = '#cbd5e1',
    children,
  } = $props();

  let isOpen = $state(open);

  function toggle() {
    isOpen = !isOpen;
  }
</script>

<div class="accordion-bar" style="border: 1px solid {borderColor};">
  <div
    class="accordion-header"
    style="background-color: {headerBg};"
    onclick={toggle}
    onkeydown={(e) => e.key === 'Enter' && toggle()}
    role="button"
    tabindex="0"
  >
    <div>
      <span class="accordion-title">{title}</span>
      {#if meta}
        <span class="accordion-meta">{meta}</span>
      {/if}
      {#if metaDim}
        <span class="accordion-meta-dim">{metaDim}</span>
      {/if}
    </div>
    <span class="accordion-icon" class:open={isOpen}>&#9654;</span>
  </div>
  <div class="accordion-content" class:open={isOpen}>
    <div class="accordion-inner" style="border-top: 1px solid {borderColor};">
      {@render children()}
    </div>
  </div>
</div>
