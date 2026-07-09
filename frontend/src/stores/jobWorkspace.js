// Per-job workspace position: which document each section last showed, each
// document's lines/reconcile mode, and the context band's collapse state.
// ONE localStorage key holding an LRU-capped map (retention stays trivial).
// URLs are the source of truth for what's displayed; this store only answers
// "where did I leave off?" when a bare section route or the band mounts.
export const JOB_WS_KEY = 'minibini_job_ws';
const MAX_JOBS = 50;
const DEFAULTS = () => ({ band: 'expanded', sections: {}, modes: {} });

function readAll() {
  try {
    const raw = JSON.parse(localStorage.getItem(JOB_WS_KEY));
    if (raw && Array.isArray(raw.order) && raw.jobs) return raw;
  } catch (e) { /* corrupt → start over */ }
  return { order: [], jobs: {} };
}

function writeJob(jobId, patch) {
  const id = String(jobId);
  const all = readAll();
  const state = { ...DEFAULTS(), ...(all.jobs[id] || {}) };
  const next = { ...state, ...patch };
  all.jobs[id] = next;
  all.order = all.order.filter((j) => j !== id);
  all.order.push(id);
  while (all.order.length > MAX_JOBS) {
    delete all.jobs[all.order.shift()];
  }
  localStorage.setItem(JOB_WS_KEY, JSON.stringify(all));
}

export function getJobWs(jobId) {
  const entry = readAll().jobs[String(jobId)];
  return { ...DEFAULTS(), ...(entry || {}) };
}

export function rememberSection(jobId, section, docId) {
  const { sections } = getJobWs(jobId);
  writeJob(jobId, { sections: { ...sections, [section]: String(docId) } });
}

export function rememberMode(jobId, docId, mode) {
  const { modes } = getJobWs(jobId);
  writeJob(jobId, { modes: { ...modes, [String(docId)]: mode } });
}

export function rememberBand(jobId, state) {
  writeJob(jobId, { band: state });
}
