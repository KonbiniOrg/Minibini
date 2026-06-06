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
// Superuser note: the backend already folds superuser into the `permissions`
// list (`get_all_permissions()` returns every permission for a superuser, so
// `/api/auth/me/` includes all atoms). `/api/auth/me/` also exposes the
// `is_superuser` flag (see UserSerializer), so the explicit check below is a
// real, functioning belt-and-suspenders safety net: these stores stay correct
// even if that permission-folding behavior ever changes.
function hasAtom(u, atom) {
  if (!u) return false;
  if (u.is_superuser) return true;
  return (u.permissions || []).includes(atom);
}

export const canManageJobs = derived(user, (u) => hasAtom(u, 'can_manage_jobs'));
export const canManageFinancials = derived(user, (u) => hasAtom(u, 'can_manage_financials'));
export const canManageTime = derived(user, (u) => hasAtom(u, 'can_manage_time'));
export const canManageConfig = derived(user, (u) => hasAtom(u, 'can_manage_config'));
