import { errorMessage } from './api.js';

/**
 * Route an api.js error to the right display venue (the display half of the
 * error contract — architecture-and-conventions.md §3.9):
 *
 *   const t = triageError(e);
 *   if (t.overlay) showError(t.overlay);   // infrastructure / no-form venue
 *   else { formError = t.message; errors = t.fields; }
 *
 * - `overlay`: set (a display string) when the error carries nothing a form
 *   can act on — no JSON body (backend down, HTML error page) or any 5xx.
 * - `message`: the form-footer text — an operation error's `detail`, or a
 *   field-keyed body's `non_field_errors`.
 * - `fields`: the field→messages bag for FieldError slots under inputs.
 *
 * Forms with no inputs of their own (plain action buttons) can pass
 * everything to the overlay instead: `showError(errorMessage(e))`.
 */
export function triageError(err) {
  const data = err?.data;
  if (!data || typeof data !== 'object' || (err.status && err.status >= 500)) {
    return { overlay: errorMessage(err), message: '', fields: {} };
  }
  if (typeof data.detail === 'string' || typeof data.error === 'string') {
    // Operation error: detail is the whole story; sibling keys (code,
    // atom_ids...) are machine payload for flow decisions — e.g. the 409
    // estimates/invoicing throw on claim conflicts: {detail, code:
    // 'atoms_already_claimed', atom_ids}.
    return { overlay: null, message: errorMessage(err), fields: {} };
  }
  const { non_field_errors, ...fields } = data;
  const message = Array.isArray(non_field_errors)
    ? non_field_errors.join(' ')
    : (typeof non_field_errors === 'string' ? non_field_errors : '');
  return { overlay: null, message, fields };
}
