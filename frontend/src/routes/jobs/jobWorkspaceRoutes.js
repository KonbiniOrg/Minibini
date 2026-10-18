// Every /jobs/:id[/section] route, as svelte-spa-router entries. Kept in one
// module so App.svelte spreads them and the router test mounts the real table.
//
// All entries point at ONE wrapped object. svelte-spa-router decides whether
// to remount by comparing the route's stored component object
// (Router.svelte: `if (componentObj != obj)`), and each wrap() call — or each
// bare component entry, which the router wraps in its own fresh closure —
// is a distinct object. Twelve wrap() calls would therefore remount
// JobWorkspace on every tab switch; one shared object keeps it mounted, so
// the shell persists across tab switches (issue #511). This also
// means the entries cannot carry per-route props: JobWorkspace reads its
// section and params from the URL (see the note in JobWorkspace.svelte).
import { wrap } from 'svelte-spa-router/wrap';
import JobWorkspace from './JobWorkspace.svelte';

const jobWorkspace = wrap({ component: JobWorkspace });

export const jobWorkspaceRoutes = {
  '/jobs/:id': jobWorkspace,
  '/jobs/:id/history': jobWorkspace,
  '/jobs/:jobId/shipments': jobWorkspace,
  '/jobs/:jobId/estimate': jobWorkspace,
  '/jobs/:jobId/estimate/:docId': jobWorkspace,
  '/jobs/:jobId/change-order/:coId': jobWorkspace,
  '/jobs/:jobId/invoice': jobWorkspace,
  '/jobs/:jobId/invoice/:docId': jobWorkspace,
  '/jobs/:jobId/tasks': jobWorkspace,
  '/jobs/:jobId/pos': jobWorkspace,
  '/jobs/:jobId/emails': jobWorkspace,
  '/jobs/:id/tasklist': jobWorkspace,
};
