// Svelte action giving a modal the standard keyboard shortcuts:
//   Enter  → save   (the modal's primary/confirm action)
//   Escape → cancel (close without saving)
//
// Attach it to the modal's overlay/backdrop element so the window listener
// lives exactly as long as the modal is on screen — when the modal is torn
// down (e.g. its `{#if open}` goes false) the listener is removed, so it
// never fires for a closed modal and several modals don't stomp each other.
//
//   <div class="overlay" use:modalKeys={{ onSave: save, onCancel: onClose }}>
//
// Enter is deliberately ignored when focus is in a <textarea> or a
// contenteditable region (so multi-line fields keep inserting newlines
// rather than submitting), on a <button> (so the focused button's own
// click isn't double-fired), and mid-IME-composition. onSave/onCancel are
// the caller's hooks; pass guards there (busy flags, confirm sub-states).
//
// Omit onSave to get an Escape-only modal. Do this when Enter is already
// handled natively by a <form> (binding it here too would double-fire), or
// when the primary action is ambiguous (several action buttons). With no
// onSave the action leaves Enter completely alone — it never preventDefaults
// it, so a native form submit still works.
export function modalKeys(node, params = {}) {
  let opts = params;

  function onKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      opts.onCancel?.();
      return;
    }
    if (e.key === 'Enter' && !e.isComposing && opts.onSave) {
      const t = e.target;
      const tag = t && t.tagName;
      if (tag === 'TEXTAREA' || tag === 'BUTTON' || (t && t.isContentEditable)) return;
      e.preventDefault();
      opts.onSave();
    }
  }

  window.addEventListener('keydown', onKeydown);
  return {
    update(next) { opts = next || {}; },
    destroy() { window.removeEventListener('keydown', onKeydown); },
  };
}
