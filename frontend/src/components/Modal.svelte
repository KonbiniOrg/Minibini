<script>
  // THE modal shell: overlay + box + the standard keyboard wiring
  // (Enter → onSave, Escape → onCancel via lib/modalKeys). Geometry lives
  // only here so it can't drift per-modal again (PriceListPicker once
  // drifted top-anchored/oversized because every modal hand-rolled the CSS).
  //
  // - Every modal opens in the SAME place: horizontally centered, anchored
  //   --modal-top (50px) from the top — so when one modal hands off to
  //   another the user isn't chasing it around the page.
  // - `maxWidth` is the one sanctioned geometry knob (forms ~600–780px).
  // - The grab bar makes the box draggable to peek at the page behind it;
  //   position resets every time the modal opens.
  // THE KEYBOARD CONTRACT (see also frontend/README.md → Modals):
  // - Every modal passes `onCancel` — Escape always closes. A modal with
  //   internal sub-states (confirm-delete, a nested prompt) passes a smarter
  //   onCancel that backs out one level before closing.
  // - Enter: one decision — is the content a native <form>? If YES, the form
  //   owns Enter (native submit + required-validation); omit `onSave` here,
  //   binding both would double-fire. If NO (button-driven content), pass
  //   `onSave`. Deliberately Esc-only modals (an ambiguous primary action)
  //   omit onSave WITH a comment saying why.
  // - `busy`: pass the modal's in-flight flag; the shell suppresses Enter
  //   while it's true, so no modal needs its own `if (!busy)` wrapper (the
  //   Save button still wants `disabled={busy}` for the click path).
  import { modalKeys } from '../lib/modalKeys.js';

  let {
    open = false,
    onSave = undefined,
    onCancel = () => {},
    busy = false,
    maxWidth = '750px',
    label = undefined,
    children,
  } = $props();

  // The busy-guard lives HERE, once — a double-Enter during a slow save must
  // never fire the API twice.
  const guardedSave = $derived(
    onSave ? () => { if (!busy) onSave(); } : undefined
  );

  // Drag offset, applied as a transform. Reset on every open so a modal
  // never reopens where its predecessor was dragged to.
  let dx = $state(0);
  let dy = $state(0);
  let grip = null;

  $effect(() => {
    if (open) { dx = 0; dy = 0; }
  });

  function startDrag(e) {
    grip = { x: e.clientX - dx, y: e.clientY - dy };
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* jsdom */ }
  }
  function moveDrag(e) {
    if (!grip) return;
    dx = e.clientX - grip.x;
    dy = e.clientY - grip.y;
  }
  function endDrag() { grip = null; }
</script>

{#if open}
  <div class="overlay" use:modalKeys={{ onSave: guardedSave, onCancel }}>
    <div
      class="modal"
      role="dialog"
      aria-label={label}
      style:max-width={maxWidth}
      style:transform={`translate(${dx}px, ${dy}px)`}
    >
      <div
        class="grab-bar"
        role="presentation"
        title="Drag to move"
        onpointerdown={startDrag}
        onpointermove={moveDrag}
        onpointerup={endDrag}
        onpointercancel={endDrag}
      ></div>
      {@render children?.()}
    </div>
  </div>
{/if}

<style>
  .overlay {
    /* --modal-top: where every modal's box anchors. One knob, tune freely. */
    --modal-top: 50px;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: var(--modal-top) 0 2em;
    z-index: var(--z-modal);
    overflow-y: auto;
  }
  .modal {
    background: white;
    padding: 16px;
    border: 1px solid #ccc;
    width: 90%;
  }
  .grab-bar {
    height: 12px;
    margin: -16px -16px 8px;   /* bleed to the box edges above the content */
    cursor: move;
    touch-action: none;
    background:
      radial-gradient(circle, #c9c9c9 1.2px, transparent 1.4px) center / 8px 6px repeat-x;
    background-color: #f5f5f5;
    border-bottom: 1px solid #eee;
  }
</style>
