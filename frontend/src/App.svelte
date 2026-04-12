<script>
  import Router, { location } from 'svelte-spa-router';
  import Sidebar from './components/Sidebar.svelte';
  import CurrentBlepBand from './components/CurrentBlepBand.svelte';
  import { user, authChecked, checkAuth } from './stores/auth.js';
  import { refreshCurrentBlep, currentBlep } from './stores/currentBlep.js';
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
  import TaskDetailPage from './routes/jobs/TaskDetailPage.svelte';
  import SettingsPage from './routes/SettingsPage.svelte';
  import InvoiceDetailPage from './routes/invoices/InvoiceDetailPage.svelte';
  import InvoiceWizardPage from './routes/invoices/InvoiceWizardPage.svelte';
  import JobBoardPage from './routes/jobs/JobBoardPage.svelte';
  import ProfilePage from './routes/ProfilePage.svelte';
  import SearchPage from './routes/Search.svelte';
  import WorksheetDetailPage from './routes/worksheets/WorksheetDetailPage.svelte';
  import WorkOrderDetailPage from './routes/workorders/WorkOrderDetailPage.svelte';
  import PurchaseOrderListPage from './routes/purchaseorders/PurchaseOrderListPage.svelte';
  import PurchaseOrderDetailPage from './routes/purchaseorders/PurchaseOrderDetailPage.svelte';
  import PurchaseOrderFormPage from './routes/purchaseorders/PurchaseOrderFormPage.svelte';
  import UserListPage from './routes/users/UserListPage.svelte';
  import UserCreatePage from './routes/users/UserCreatePage.svelte';
  import UserDetailPage from './routes/users/UserDetailPage.svelte';
  import ExpenseListPage from './routes/expenses/ExpenseListPage.svelte';
  import ReimbursementDetailPage from './routes/reimbursements/ReimbursementDetailPage.svelte';

  const routes = {
    '/': Home,
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
    '/jobs/:id': JobDetailPage,
    '/jobs/:jobId/tasks/:taskId': TaskDetailPage,
    '/worksheets/:id': WorksheetDetailPage,
    '/work-orders/:id': WorkOrderDetailPage,
    '/purchase-orders': PurchaseOrderListPage,
    '/purchase-orders/new': PurchaseOrderFormPage,
    '/purchase-orders/:id/edit': PurchaseOrderFormPage,
    '/purchase-orders/:id': PurchaseOrderDetailPage,
    '/invoices/:id/wizard': InvoiceWizardPage,
    '/invoices/:id': InvoiceDetailPage,
    '/settings': SettingsPage,
    '/users': UserListPage,
    '/users/new': UserCreatePage,
    '/users/:id': UserDetailPage,
    '/expenses': ExpenseListPage,
    '/reimbursements/:id': ReimbursementDetailPage,
    '/profile': ProfilePage,
  };

  let sidebarOpen = $state(false);

  checkAuth();

  // Refresh the global current-Blep band on auth + every SPA route change.
  $effect(() => {
    if ($user) {
      // Touch $location so this effect re-runs on navigation.
      $location;
      refreshCurrentBlep();
    } else {
      currentBlep.set(null);
    }
  });
</script>

{#if !$authChecked}
  <p>Loading...</p>
{:else if !$user}
  <LoginPage />
{:else}
  <CurrentBlepBand />
  <Sidebar bind:open={sidebarOpen} />
  <!--
    Push behavior: margin-left shifts content when sidebar opens.
    To switch to overlay: remove the style:margin-left line below.
  -->
  <div class="page-content" style:margin-left={sidebarOpen ? '120px' : '0'}>
    <Router {routes} />
  </div>
{/if}

<style>
  .page-content {
    transition: margin-left 0.25s ease;
    padding-top: 8px;
  }
</style>
