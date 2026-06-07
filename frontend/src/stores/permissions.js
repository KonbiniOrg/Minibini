import { derived } from 'svelte/store';
import { user } from './auth.js';

// Per-atom derived permission stores, the single source of truth for SPA
// permission gating. Use these instead of hand-rolling
// `$user?.permissions?.includes('can_manage_x')` in each component — that
// boilerplate drifted (some components forgot to derive an atom at all, so a
// mutating button showed to users the backend then 403'd). Naming the atom a
// gate requires also makes "is this gated?" greppable in review.
//
// The four atoms mirror the backend's custom permissions
// (`docs/designs/users-and-permissions.md` §3): a gate here should match the
// atom the action's endpoint enforces in its DRF viewset.
//
// Authorization is atoms-only: there is no superuser special-case. A Django
// superuser still passes every gate because `get_all_permissions()` folds all
// permissions into the `permissions` list `/api/auth/me/` returns.
function hasAtom(u, atom) {
  if (!u) return false;
  return (u.permissions || []).includes(atom);
}

export const canManageJobs = derived(user, (u) => hasAtom(u, 'can_manage_jobs'));
export const canManageFinancials = derived(user, (u) => hasAtom(u, 'can_manage_financials'));
export const canManageTime = derived(user, (u) => hasAtom(u, 'can_manage_time'));
export const canManageConfig = derived(user, (u) => hasAtom(u, 'can_manage_config'));
