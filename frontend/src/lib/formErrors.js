/**
 * Read DRF-style field errors from an error-bag object, always
 * returning an array (so `{#each}` works cleanly). Returns [] if
 * the field isn't present.
 */
export function fieldErrors(errors, field) {
  const v = errors?.[field];
  if (!v) return [];
  return Array.isArray(v) ? v : [v];
}
