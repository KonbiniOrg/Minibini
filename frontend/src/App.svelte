<script>
  import Router, { location, replace } from 'svelte-spa-router';
  import { wrap } from 'svelte-spa-router/wrap';
  import RedirectTo from './routes/RedirectTo.svelte';
  import { setupStatus, refreshSetupStatus, areaUnavailable } from './stores/setupStatus.js';
  import Sidebar from './components/Sidebar.svelte';
  import CurrentBlepBand from './components/CurrentBlepBand.svelte';
  import ShiftBand from './components/ShiftBand.svelte';
  import MessageOverlay from './components/MessageOverlay.svelte';
  import { user, authChecked, checkAuth } from './stores/auth.js';
  import { refreshCurrentBlep, currentBlep } from './stores/currentBlep.js';
  import { refreshCurrentShift, currentShift } from './stores/shift.js';
  import LoginPage from './routes/LoginPage.svelte';
  import Home from './routes/Home.svelte';
  import ContactListPage from './routes/contacts/ContactListPage.svelte';
  import ContactDetailPage from './routes/contacts/ContactDetailPage.svelte';
  import BusinessListPage from './routes/contacts/BusinessListPage.svelte';
  import BusinessDetailPage from './routes/contacts/BusinessDetailPage.svelte';
  import JobListPage from './routes/jobs/JobListPage.svelte';
  import JobRedirectToOverview from './routes/jobs/JobRedirectToOverview.svelte';
  import TaskDetailPage from './routes/jobs/TaskDetailPage.svelte';
  import { jobWorkspaceRoutes } from './routes/jobs/jobWorkspaceRoutes.js';
  import SettingsPage from './routes/SettingsPage.svelte';
  import CatalogInventoryPage from './routes/catalog/CatalogInventoryPage.svelte';
  import CatalogServiceItemsPage from './routes/catalog/CatalogServiceItemsPage.svelte';
  import CatalogEarmarksPage from './routes/catalog/CatalogEarmarksPage.svelte';
  import InvoiceDetailPage from './routes/invoices/InvoiceDetailPage.svelte';
  import InvoiceListPage from './routes/invoices/InvoiceListPage.svelte';
  import InvoiceWizardRedirect from './routes/invoices/InvoiceWizardRedirect.svelte';
  import JobBoardPage from './routes/jobs/JobBoardPage.svelte';
  import SchedulePage from './routes/schedule/SchedulePage.svelte';
  import SearchPage from './routes/Search.svelte';
  import EstimateDetailPage from './routes/estimates/EstimateDetailPage.svelte';
  import EstimateWizardRedirect from './routes/estimates/EstimateWizardRedirect.svelte';
  import PackingListPrint from './routes/shipments/PackingListPrint.svelte';
  import PurchaseOrderListPage from './routes/purchaseorders/PurchaseOrderListPage.svelte';
  import PurchaseOrderDetailPage from './routes/purchaseorders/PurchaseOrderDetailPage.svelte';
  import PurchaseOrderSendPage from './routes/purchaseorders/PurchaseOrderSendPage.svelte';
  import PurchaseOrderFormPage from './routes/purchaseorders/PurchaseOrderFormPage.svelte';
  import UserListPage from './routes/users/UserListPage.svelte';
  import UserDetailPage from './routes/users/UserDetailPage.svelte';
  import ExpenseListPage from './routes/expenses/ExpenseListPage.svelte';
  import ReimbursementDetailPage from './routes/reimbursements/ReimbursementDetailPage.svelte';
  import EmailInboxPage from './routes/email/EmailInboxPage.svelte';
  import EmailDetailPage from './routes/email/EmailDetailPage.svelte';
  import ActivityPage from './routes/ActivityPage.svelte';
  import ChangeOrderRedirect from './routes/change-orders/ChangeOrderRedirect.svelte';
  import LoadState from './components/LoadState.svelte';

  const routes = {
    '/': Home,
    '/activity': ActivityPage,
    '/search': SearchPage,
    '/contacts': ContactListPage,
    '/contacts/new': wrap({ component: RedirectTo, props: { to: '/contacts' } }),
    '/contacts/:id/edit': wrap({ component: RedirectTo, props: { to: '/contacts/:id' } }),
    '/contacts/:id': ContactDetailPage,
    '/businesses': BusinessListPage,
    '/businesses/new': wrap({ component: RedirectTo, props: { to: '/businesses' } }),
    '/businesses/:id/edit': wrap({ component: RedirectTo, props: { to: '/businesses/:id' } }),
    '/businesses/:id': BusinessDetailPage,
    '/jobs': JobListPage,
    '/jobs/new': wrap({ component: RedirectTo, props: { to: '/jobs/board' } }),
    '/jobs/board': JobBoardPage,
    '/schedule': SchedulePage,
    // Every /jobs/:id[/section] route → the one persistent JobWorkspace
    // (jobWorkspaceRoutes.js). Routes are exact-match, so the standalone
    // entries below can sit alongside without ordering concerns.
    ...jobWorkspaceRoutes,
    '/jobs/:id/edit': JobRedirectToOverview,
    '/jobs/:id/duplicate': JobRedirectToOverview,
    '/jobs/:jobId/tasks/:taskId': TaskDetailPage,
    '/shipments/:sid/print': PackingListPrint,
    '/estimates/:id/wizard': EstimateWizardRedirect,
    '/estimates/:id/send': wrap({ component: RedirectTo, props: { to: '/estimates/:id' } }),
    '/estimates/:id': EstimateDetailPage,
    '/purchase-orders': PurchaseOrderListPage,
    '/purchase-orders/new': PurchaseOrderFormPage,
    '/purchase-orders/:id/edit': PurchaseOrderFormPage,
    '/purchase-orders/:id/send': PurchaseOrderSendPage,
    '/purchase-orders/:id': PurchaseOrderDetailPage,
    '/invoices': InvoiceListPage,
    '/invoices/:id/wizard': InvoiceWizardRedirect,
    '/invoices/:id/send': wrap({ component: RedirectTo, props: { to: '/invoices/:id' } }),
    '/invoices/:id': InvoiceDetailPage,
    '/settings': SettingsPage,
    '/catalog': CatalogInventoryPage,
    '/catalog/service-items': CatalogServiceItemsPage,
    '/catalog/earmarks': CatalogEarmarksPage,
    '/users': UserListPage,
    '/users/new': wrap({ component: RedirectTo, props: { to: '/users' } }),
    '/users/:id': UserDetailPage,
    '/expenses': ExpenseListPage,
    '/reimbursements/:id': ReimbursementDetailPage,
    '/email': EmailInboxPage,
    '/email/:id/create-job': wrap({ component: RedirectTo, props: { to: '/email/:id' } }),
    '/email/:id/create-po': wrap({ component: RedirectTo, props: { to: '/email/:id' } }),
    '/email/:id/associate': wrap({ component: RedirectTo, props: { to: '/email/:id' } }),
    '/email/:id/associate-po': wrap({ component: RedirectTo, props: { to: '/email/:id' } }),
    '/email/:id': EmailDetailPage,
    // Home with the Profile / Help tab active (tab derived from location
    // in Home).
    '/profile': Home,
    '/help': Home,
    '/change-orders/:id/send': wrap({ component: RedirectTo, props: { to: '/change-orders/:id' } }),
    '/change-orders/:id': ChangeOrderRedirect,
  };

  checkAuth();

  // Session expiry: api.js dispatches this when an authenticated-only call
  // comes back unauthenticated. Drop to the login screen with a notice
  // instead of letting each component degrade silently.
  let sessionExpired = $state(false);
  $effect(() => {
    function onExpired() {
      if ($user) {
        sessionExpired = true;
        user.set(null);
      }
    }
    window.addEventListener('minibini:session-expired', onExpired);
    return () => window.removeEventListener('minibini:session-expired', onExpired);
  });
  $effect(() => {
    if ($user) sessionExpired = false;
  });

  // Setup gating: load gate state on auth; redirect greyed areas Home.
  const GATED_ROUTE_PREFIXES = [
    ['/jobs', 'jobs'], ['/email', 'email'],
    ['/purchase-orders', 'purchasing'], ['/catalog', 'catalog'],
    ['/invoices', 'invoices'], ['/estimates', 'estimates'],
  ];
  $effect(() => {
    if (!$user) return;
    $setupStatus;  // re-run when gates load/refresh
    const path = $location;
    for (const [prefix, area] of GATED_ROUTE_PREFIXES) {
      if (path.startsWith(prefix) && areaUnavailable(area)) {
        replace('/');
        return;
      }
    }
  });

  // Refresh the global shift + current-Blep bands and the setup gate
  // state on auth + every SPA route change (standard refresh pattern).
  $effect(() => {
    if ($user) {
      // Touch $location so this effect re-runs on navigation.
      $location;
      refreshCurrentBlep();
      refreshCurrentShift();
      refreshSetupStatus();
    } else {
      currentBlep.set(null);
      currentShift.set(null);
    }
  });
</script>

<LoadState loading={!$authChecked}>
{#if !$user}
  <LoginPage notice={sessionExpired ? 'Your session expired — please log in again.' : ''} />
{:else}
  <!-- Permanent shift strip; the timeslip band slides in beneath it while a
       session runs. One sticky wrapper so the pair pins as a unit. -->
  <header class="app-bands">
    <ShiftBand />
    <CurrentBlepBand />
  </header>
  <Sidebar />
  <!--
    Overlay behavior: the sidebar is position:fixed at the --z-sidebar tier
    (see the z-index scale in css/app.css), so it slides in on top of the page
    without shifting content.
  -->
  <div class="page-content">
    <Router {routes} />
  </div>
  <MessageOverlay />
{/if}
</LoadState>

<style>
  .app-bands {
    position: sticky;
    top: 0;
    z-index: var(--z-sticky);
  }
</style>
