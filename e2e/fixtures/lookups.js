// Locate backdrop rows by SHAPE, not by hardcoded pk — robust across seed
// re-dumps. A spec that can't find its shape skips with a named seed gap, so
// the run output doubles as the seed-sufficiency report
// (docs/designs/e2e-testing.md §3).
import { apiAs } from './api.js';
import { personas } from './personas.js';

// One shot: every job with embedded tasks (status, qty_source) and
// materials (consumption_state, quantity, qty_on_hand, task, inventory_item).
export async function loadBackdrop() {
  const api = await apiAs(personas.finjobs);
  const jobs = (await api.get('/api/jobs/?page_size=100')).results;
  await api.dispose();
  return jobs;
}

const stocked = (m) => Number(m.qty_on_hand) >= Number(m.quantity);

export const pendingTasks = (job) =>
  (job.tasks || []).filter((t) => t.status === 'pending');

export const taskMaterials = (job, task) =>
  (job.materials || []).filter(
    (m) => m.task === task.task_id && m.consumption_state === 'pending');

export const looseMaterials = (job) =>
  (job.materials || []).filter(
    (m) => !m.task && m.consumption_state === 'pending' && Number(m.quantity) > 0);

// Find a pending task matching the wanted shape. `used` is a Set of job ids
// already claimed by earlier tests in the run — each test mutates its job, so
// no two tests may share one.
export function findStartableTask(jobs, {
  jobStatus,            // exact job status, or an array of them
  algorithm,            // 'elapsed_time' | 'entered_qty'
  materials,            // 'in-stock' (≥1, all stocked) | 'shortfall' (≥1 short) | 'none'
  minPendingTasks = 1,
  used = new Set(),
} = {}) {
  const statuses = Array.isArray(jobStatus) ? jobStatus : jobStatus && [jobStatus];
  for (const job of jobs) {
    if (used.has(job.job_id) || job.on_hold) continue;
    if (statuses && !statuses.includes(job.status)) continue;
    const pending = pendingTasks(job);
    if (pending.length < minPendingTasks) continue;
    for (const task of pending) {
      // qty_source is the task's own field (task-owned-money Phase 1) —
      // was scheme_algorithm, an echo of the RateScheme it stamped from.
      if (algorithm && task.qty_source !== algorithm) continue;
      const mats = taskMaterials(job, task);
      if (materials === 'in-stock' && !(mats.length > 0 && mats.every(stocked))) continue;
      if (materials === 'shortfall' && !mats.some((m) => !stocked(m))) continue;
      if (materials === 'none' && mats.length > 0) continue;
      used.add(job.job_id);
      return { job, task, mats };
    }
  }
  return null;
}

// Find a job in `jobStatus` carrying an estimate in `estimateStatus`
// (async — the backdrop list can't answer this: has_estimates is detail-only
// and estimate statuses live on /api/estimates/). Candidates are tried
// poorest-first (fewest pending tasks) so shape-rich jobs stay available for
// specs that need multi-task setups. Returns { job, estimate } or null.
export async function findJobWithEstimate(jobs, {
  jobStatus, estimateStatus, used = new Set(),
} = {}) {
  const api = await apiAs(personas.finjobs);
  try {
    const candidates = jobs
      .filter((j) => !used.has(j.job_id) && !j.on_hold && j.status === jobStatus)
      .sort((a, b) => pendingTasks(a).length - pendingTasks(b).length);
    for (const job of candidates) {
      const resp = await api.get(`/api/estimates/?job=${job.job_id}`);
      const list = resp?.results || resp || [];
      const estimate = list.find((e) => e.status === estimateStatus);
      if (estimate) {
        used.add(job.job_id);
        return { job, estimate };
      }
    }
    return null;
  } finally {
    await api.dispose();
  }
}

export function findJob(jobs, { status, withLoosePending, singleOpenTask, used = new Set() } = {}) {
  for (const job of jobs) {
    if (used.has(job.job_id) || job.on_hold) continue;
    if (status && job.status !== status) continue;
    if (withLoosePending && looseMaterials(job).length === 0) continue;
    if (singleOpenTask) {
      const open = (job.tasks || []).filter(
        (t) => !['complete', 'cancelled'].includes(t.status));
      if (open.length !== 1 || open[0].status !== 'pending') continue;
    }
    used.add(job.job_id);
    return job;
  }
  return null;
}
