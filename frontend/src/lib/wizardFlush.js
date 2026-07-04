// A tiny registry so a wizard's "Done" can flush every line-item card's pending
// (unsaved) edit before navigating away. Each WizardLineItemCard registers its
// save function by line-item id; flushAll() runs them all (each is a no-op when
// the card is clean) and THROWS if any fail, so the caller can keep the user on
// the wizard instead of silently losing the edit.
export function createFlushRegistry() {
  const flushers = new Map();
  return {
    // Pass a function to register, or null/undefined to unregister (on unmount).
    register(id, fn) {
      if (fn) flushers.set(id, fn);
      else flushers.delete(id);
    },
    async flushAll() {
      // allSettled (not all): attempt EVERY dirty card even if one fails, so the
      // user saves as much as possible; then surface a failure if any rejected.
      const results = await Promise.allSettled([...flushers.values()].map((f) => f()));
      const failed = results.filter((r) => r.status === 'rejected');
      if (failed.length) {
        throw new Error(
          `${failed.length} change${failed.length > 1 ? 's' : ''} could not be saved.`,
        );
      }
    },
  };
}
