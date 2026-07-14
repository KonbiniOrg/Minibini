<script>
  import Router, { location } from 'svelte-spa-router';
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
  import ContactFormPage from './routes/contacts/ContactFormPage.svelte';
  import BusinessListPage from './routes/contacts/BusinessListPage.svelte';
  import BusinessDetailPage from './routes/contacts/BusinessDetailPage.svelte';
  import BusinessFormPage from './routes/contacts/BusinessFormPage.svelte';
  import JobListPage from './routes/jobs/JobListPage.svelte';
  import JobDetailPage from './routes/jobs/JobDetailPage.svelte';
  import JobRedirectToOverview from './routes/jobs/JobRedirectToOverview.svelte';
  import TaskDetailPage from './routes/jobs/TaskDetailPage.svelte';
  import SettingsPage from './routes/SettingsPage.svelte';
  import CatalogInventoryPage from './routes/catalog/CatalogInventoryPage.svelte';
  import CatalogServiceItemsPage from './routes/catalog/CatalogServiceItemsPage.svelte';
  import CatalogEarmarksPage from './routes/catalog/CatalogEarmarksPage.svelte';
  import InvoiceDetailPage from './routes/invoices/InvoiceDetailPage.svelte';
  import InvoiceListPage from './routes/invoices/InvoiceListPage.svelte';
  import InvoiceSendPage from './routes/invoices/InvoiceSendPage.svelte';
  import InvoiceWizardRedirect from './routes/invoices/InvoiceWizardRedirect.svelte';
  import BillListPage from './routes/bills/BillListPage.svelte';
  import BillFormPage from './routes/bills/BillFormPage.svelte';
  import BillDetailPage from './routes/bills/BillDetailPage.svelte';
  import JobBoardPage from './routes/jobs/JobBoardPage.svelte';
  import SchedulePage from './routes/schedule/SchedulePage.svelte';
  import SearchPage from './routes/Search.svelte';
  import EstimateDetailPage from './routes/estimates/EstimateDetailPage.svelte';
  import EstimateSendPage from './routes/estimates/EstimateSendPage.svelte';
  import EstimateWizardRedirect from './routes/estimates/EstimateWizardRedirect.svelte';
  import JobTaskListPage from './routes/jobs/JobTaskListPage.svelte';
  import JobShipmentsPage from './routes/jobs/JobShipmentsPage.svelte';
  import JobEstimatePage from './routes/jobs/JobEstimatePage.svelte';
  import JobInvoicePage from './routes/jobs/JobInvoicePage.svelte';
  import JobHistoryPage from './routes/jobs/JobHistoryPage.svelte';
  import JobPOsPage from './routes/jobs/JobPOsPage.svelte';
  import JobEmailsPage from './routes/jobs/JobEmailsPage.svelte';
  import PackingListPrint from './routes/shipments/PackingListPrint.svelte';
  import PurchaseOrderListPage from './routes/purchaseorders/PurchaseOrderListPage.svelte';
  import PurchaseOrderDetailPage from './routes/purchaseorders/PurchaseOrderDetailPage.svelte';
  import PurchaseOrderSendPage from './routes/purchaseorders/PurchaseOrderSendPage.svelte';
  import PurchaseOrderFormPage from './routes/purchaseorders/PurchaseOrderFormPage.svelte';
  import UserListPage from './routes/users/UserListPage.svelte';
  import UserCreatePage from './routes/users/UserCreatePage.svelte';
  import UserDetailPage from './routes/users/UserDetailPage.svelte';
  import ExpenseListPage from './routes/expenses/ExpenseListPage.svelte';
  import ReimbursementDetailPage from './routes/reimbursements/ReimbursementDetailPage.svelte';
  import EmailInboxPage from './routes/email/EmailInboxPage.svelte';
  import EmailDetailPage from './routes/email/EmailDetailPage.svelte';
  import EmailCreateJobPage from './routes/email/EmailCreateJobPage.svelte';
  import EmailCreatePOPage from './routes/email/EmailCreatePOPage.svelte';
  import EmailCreateBillPage from './routes/email/EmailCreateBillPage.svelte';
  import EmailAssociatePage from './routes/email/EmailAssociatePage.svelte';
  import EmailAssociatePOPage from './routes/email/EmailAssociatePOPage.svelte';
  import EmailAssociateBillPage from './routes/email/EmailAssociateBillPage.svelte';
  import ActivityPage from './routes/ActivityPage.svelte';
  import ChangeOrderDetailPage from './routes/change-orders/ChangeOrderDetailPage.svelte';
  import ChangeOrderRedirect from './routes/change-orders/ChangeOrderRedirect.svelte';
  import ChangeOrderSendPage from './routes/change-orders/ChangeOrderSendPage.svelte';

  const routes = {
    '/': Home,
    '/activity': ActivityPage,
    '/search': SearchPage,
    '/contacts': ContactListPage,
    '/contacts/new': ContactFormPage,
    '/contacts/:id/edit': ContactFormPage,
    '/contacts/:id': ContactDetailPage,
    '/businesses': BusinessListPage,
    '/businesses/new': BusinessFormPage,
    '/businesses/:id/edit': BusinessFormPage,
    '/businesses/:id': BusinessDetailPage,
    '/jobs': JobListPage,
    '/jobs/board': JobBoardPage,
    '/schedule': SchedulePage,
    '/jobs/:id': JobDetailPage,
    '/jobs/:id/edit': JobRedirectToOverview,
    '/jobs/:id/duplicate': JobRedirectToOverview,
    '/jobs/:id/history': JobHistoryPage,
    '/jobs/:jobId/shipments': JobShipmentsPage,
    '/jobs/:jobId/estimate': JobEstimatePage,
    '/jobs/:jobId/estimate/:docId': JobEstimatePage,
    '/jobs/:jobId/change-order/:coId': ChangeOrderDetailPage,
    '/jobs/:jobId/invoice': JobInvoicePage,
    '/jobs/:jobId/invoice/:docId': JobInvoicePage,
    '/jobs/:jobId/tasks': JobTaskListPage,
    '/jobs/:jobId/tasks/:taskId': TaskDetailPage,
    '/jobs/:jobId/pos': JobPOsPage,
    '/jobs/:jobId/emails': JobEmailsPage,
    '/jobs/:id/tasklist': JobTaskListPage,
    '/shipments/:sid/print': PackingListPrint,
    '/estimates/:id/wizard': EstimateWizardRedirect,
    '/estimates/:id/send': EstimateSendPage,
    '/estimates/:id': EstimateDetailPage,
    '/purchase-orders': PurchaseOrderListPage,
    '/purchase-orders/new': PurchaseOrderFormPage,
    '/purchase-orders/:id/edit': PurchaseOrderFormPage,
    '/purchase-orders/:id/send': PurchaseOrderSendPage,
    '/purchase-orders/:id': PurchaseOrderDetailPage,
    '/invoices': InvoiceListPage,
    '/invoices/:id/wizard': InvoiceWizardRedirect,
    '/invoices/:id/send': InvoiceSendPage,
    '/invoices/:id': InvoiceDetailPage,
    '/bills': BillListPage,
    '/bills/new': BillFormPage,
    '/bills/:id/edit': BillFormPage,
    '/bills/:id': BillDetailPage,
    '/settings': SettingsPage,
    '/catalog': CatalogInventoryPage,
    '/catalog/service-items': CatalogServiceItemsPage,
    '/catalog/earmarks': CatalogEarmarksPage,
    '/users': UserListPage,
    '/users/new': UserCreatePage,
    '/users/:id': UserDetailPage,
    '/expenses': ExpenseListPage,
    '/reimbursements/:id': ReimbursementDetailPage,
    '/email': EmailInboxPage,
    '/email/:id/create-job': EmailCreateJobPage,
    '/email/:id/create-po': EmailCreatePOPage,
    '/email/:id/create-bill': EmailCreateBillPage,
    '/email/:id/associate': EmailAssociatePage,
    '/email/:id/associate-po': EmailAssociatePOPage,
    '/email/:id/associate-bill': EmailAssociateBillPage,
    '/email/:id': EmailDetailPage,
    // Home with the Profile / Help tab active (tab derived from location
    // in Home).
    '/profile': Home,
    '/help': Home,
    '/change-orders/:id/send': ChangeOrderSendPage,
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

  // Refresh the global shift + current-Blep bands on auth + every SPA
  // route change.
  $effect(() => {
    if ($user) {
      // Touch $location so this effect re-runs on navigation.
      $location;
      refreshCurrentBlep();
      refreshCurrentShift();
    } else {
      currentBlep.set(null);
      currentShift.set(null);
    }
  });
</script>

{#if !$authChecked}
  <p>Loading...</p>
{:else if !$user}
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

<style>
  .app-bands {
    position: sticky;
    top: 0;
    z-index: var(--z-sticky);
  }
</style>
