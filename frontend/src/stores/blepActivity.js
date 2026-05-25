import { writable } from 'svelte/store';
import { refreshCurrentBlep } from './currentBlep.js';

// One funnel for every blep mutation (start / stop / cancel / edit / delete /
// create). Bumped on success so the sticky CurrentBlepBand re-reads
// /api/bleps/current/ (and closes itself when there's no open blep) AND any page
// showing blep-dependent data can refetch by subscribing to the version.
export const blepActivityVersion = writable(0);

export async function notifyBlepChanged() {
  await refreshCurrentBlep();
  blepActivityVersion.update((n) => n + 1);
}
