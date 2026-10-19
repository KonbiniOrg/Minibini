<script>
  // JobWorkspace: the single component mounted for every /jobs/:id[/section]
  // route. All of those routes share ONE wrapped route object
  // (jobWorkspaceRoutes.js explains why that is load-bearing), so
  // svelte-spa-router keeps this instance mounted across tab switches: the
  // shell chrome (JobHeader + JobContextBand + JobNavRail, via JobShell)
  // stays put and only the inner section body swaps, which removes the
  // reload flicker (issue #511). The job is loaded once per job and then
  // silently revalidated on each in-workspace navigation (see below) so the
  // page stays as fresh as the old remount-per-route layout kept it. Deep
  // links to every section and sub-document are preserved: the route table
  // still carries the same paths.
  import { location } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import LoadState from '../../components/LoadState.svelte';
  import TasksBody from './bodies/TasksBody.svelte';
  import POsBody from './bodies/POsBody.svelte';
  import ShipmentsBody from './bodies/ShipmentsBody.svelte';
  import EmailsBody from './bodies/EmailsBody.svelte';
  import HistoryBody from './bodies/HistoryBody.svelte';
  import EstimateBody from './bodies/EstimateBody.svelte';
  import InvoiceBody from './bodies/InvoiceBody.svelte';
  import ChangeOrderBody from './bodies/ChangeOrderBody.svelte';
  import OverviewBody from './bodies/OverviewBody.svelte';

  // svelte-spa-router passes the matched `params`, but we deliberately do not
  // read them: the router delivers them one tick AFTER `$location` changes,
  // so on a section switch (estimate/7 → invoice/9) a body keyed on the new
  // section would briefly see the old section's docId — a wrong document
  // fetch and the wrong id remembered for the section. Section and params
  // are therefore both parsed from `$location`, one synchronous source.
  let { params: _routerParams = {} } = $props();

  // `$location` is `/jobs/:id[/segment[/:sub]]`: no segment is the overview,
  // `tasklist` is the legacy alias for the task list, `:sub` is the docId for
  // estimate/invoice and the coId for change-order. Both historical param
  // names (`id` for the overview/history routes, `jobId` for sections) are
  // provided so bodies ported from the old pages read either.
  const SECTION_ALIASES = { tasklist: 'tasks' };
  const route = $derived.by(() => {
    const [, , id, seg, sub] = ($location || '').split('/');
    const section = seg ? (SECTION_ALIASES[seg] ?? seg) : 'overview';
    const params = { id, jobId: id };
    if (section === 'change-order' && sub) params.coId = sub;
    else if ((section === 'estimate' || section === 'invoice') && sub) params.docId = sub;
    return { section, params };
  });
  const section = $derived(route.section);
  const params = $derived(route.params);

  // Derive on value so a bare tab switch (new params object, same id) does
  // not retrigger the load effect below.
  const jobId = $derived(params.jobId);

  let job = $state(null);
  let contact = $state(null);
  let error = $state('');
  // Plain var, not $state: the load effect writes `job`; if it also read a
  // reactive "loaded id" it would depend on its own write and loop. This
  // tracks which job is loaded without adding a dependency.
  let loadedJobId = null;

  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      loadedJobId = String(jobId);
      contact = job?.contact
        ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null)
        : null;
    } catch (e) {
      error = errorMessage(e, 'Could not load job.');
    }
  }

  // Load only when the job actually changes. On a change to a different job,
  // drop the loaded one first: the shell under `{#if job}` unmounts and
  // mounts fresh for the new job, so per-job shell state (the context band's
  // remembered collapse) is read for the right job, and the new URL never
  // shows the old job's data while loading.
  $effect(() => {
    if (!jobId || String(jobId) === loadedJobId) return;
    if (loadedJobId !== null) {
      job = null;
      contact = null;
    }
    loadJob();
  });

  // Silent revalidation. The old one-page-per-route layout refetched the job
  // on every navigation by remounting; with a persistent shell, a navigation
  // inside the same job (tab switch, document switch) must still see
  // server-side changes made meanwhile (an estimate accepted via the API,
  // another user's edit). So every in-workspace location change re-requests
  // the job, but assigns it ONLY if the payload differs: an unchanged job
  // keeps its object identity, so nothing re-renders and no panel keyed on
  // job identity reloads; a changed one flows down the normal
  // props-down path. Never clears `job`, never shows a placeholder.
  let lastLocation = null;
  async function revalidateJob() {
    const id = jobId;
    try {
      const fresh = await api.get(`/api/jobs/${id}/`);
      if (String(id) !== loadedJobId || !job) return; // moved to another job meanwhile
      if (JSON.stringify(fresh) === JSON.stringify(job)) return;
      const contactChanged = fresh.contact !== job.contact;
      job = fresh;
      if (contactChanged) {
        contact = fresh.contact
          ? await api.get(`/api/contacts/${fresh.contact}/`).catch(() => null)
          : null;
      }
    } catch (_) {
      // Keep showing what we have; the next mutation or navigation retries.
    }
  }
  $effect(() => {
    const loc = $location;
    if (!loc || !jobId) return;
    if (lastLocation === null || lastLocation === loc) { lastLocation = loc; return; }
    lastLocation = loc;
    if (String(jobId) === loadedJobId) revalidateJob();
  });

  // section → nav-rail active key + colorway (mirrors the per-page values the
  // old section pages passed to JobShell). change-order rides the estimate
  // section's rail + colorway, as the old JobChangeOrderPage did.
  const CHROME = {
    overview:       { current: 'overview',  colorway: '' },
    estimate:       { current: 'estimate',  colorway: 'cw-estimate' },
    'change-order': { current: 'estimate',  colorway: 'cw-estimate' },
    invoice:        { current: 'invoice',   colorway: 'cw-invoice' },
    tasks:          { current: 'tasks',     colorway: 'cw-tasks' },
    pos:            { current: 'pos',       colorway: 'cw-neutral' },
    shipments:      { current: 'shipments', colorway: 'cw-neutral' },
    emails:         { current: 'emails',    colorway: 'cw-neutral' },
    history:        { current: 'history',   colorway: 'cw-neutral' },
  };
  const chrome = $derived(CHROME[section] ?? { current: section, colorway: '' });
</script>

<LoadState loading={!job && !error} {error}>
{#if job}
  <JobShell {job} {contact} current={chrome.current} colorway={chrome.colorway} onJobChange={loadJob}>
    {#if section === 'overview'}
      <OverviewBody {job} {contact} onJobChange={loadJob} />
    {:else if section === 'estimate'}
      <EstimateBody {job} {params} onJobChange={loadJob} />
    {:else if section === 'change-order'}
      <ChangeOrderBody {job} {params} onJobChange={loadJob} />
    {:else if section === 'invoice'}
      <InvoiceBody {job} {params} onJobChange={loadJob} />
    {:else if section === 'tasks'}
      <TasksBody {job} onJobChange={loadJob} />
    {:else if section === 'pos'}
      <POsBody {job} />
    {:else if section === 'shipments'}
      <ShipmentsBody {job} onJobChange={loadJob} />
    {:else if section === 'emails'}
      <EmailsBody {job} />
    {:else if section === 'history'}
      <HistoryBody {job} onJobChange={loadJob} />
    {/if}
  </JobShell>
{/if}
</LoadState>
