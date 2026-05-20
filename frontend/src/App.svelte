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
  import JobEditPage from './routes/jobs/JobEditPage.svelte';
  import CreateWorksheetPage from './routes/jobs/CreateWorksheetPage.svelte';
  import TaskDetailPage from './routes/jobs/TaskDetailPage.svelte';
  import SettingsPage from './routes/SettingsPage.svelte';
  import InvoiceDetailPage from './routes/invoices/InvoiceDetailPage.svelte';
  import InvoiceWizardPage from './routes/invoices/InvoiceWizardPage.svelte';
  import JobBoardPage from './routes/jobs/JobBoardPage.svelte';
  import SchedulePage from './routes/schedule/SchedulePage.svelte';
  import ProfilePage from './routes/ProfilePage.svelte';
  import SearchPage from './routes/Search.svelte';
  import WorksheetDetailPage from './routes/worksheets/WorksheetDetailPage.svelte';
  import PlanTaskDetailPage from './routes/worksheets/PlanTaskDetailPage.svelte';
  import EstimateDetailPage from './routes/estimates/EstimateDetailPage.svelte';
  import EstimateWizardPage from './routes/estimates/EstimateWizardPage.svelte';
  import JobTaskListPage from './routes/jobs/JobTaskListPage.svelte';
  import JobShipmentsPage from './routes/jobs/JobShipmentsPage.svelte';
  import PackingListPrint from './routes/shipments/PackingListPrint.svelte';
  import PurchaseOrderListPage from './routes/purchaseorders/PurchaseOrderListPage.svelte';
  import PurchaseOrderDetailPage from './routes/purchaseorders/PurchaseOrderDetailPage.svelte';
  import PurchaseOrderFormPage from './routes/purchaseorders/PurchaseOrderFormPage.svelte';
  import UserListPage from './routes/users/UserListPage.svelte';
  import UserCreatePage from './routes/users/UserCreatePage.svelte';
  import UserDetailPage from './routes/users/UserDetailPage.svelte';
  import ExpenseListPage from './routes/expenses/ExpenseListPage.svelte';
  import ReimbursementDetailPage from './routes/reimbursements/ReimbursementDetailPage.svelte';
  import EmailInboxPage from './routes/email/EmailInboxPage.svelte';
  import EmailDetailPage from './routes/email/EmailDetailPage.svelte';
  import EmailCreateJobPage from './routes/email/EmailCreateJobPage.svelte';
  import EmailAssociatePage from './routes/email/EmailAssociatePage.svelte';

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
    '/schedule': SchedulePage,
    '/jobs/:id': JobDetailPage,
    '/jobs/:id/edit': JobEditPage,
    '/jobs/:id/create-worksheet': CreateWorksheetPage,
    '/jobs/:id/tasklist': JobTaskListPage,
    '/jobs/:jobId/shipments': JobShipmentsPage,
    '/jobs/:jobId/tasks/:taskId': TaskDetailPage,
    '/shipments/:sid/print': PackingListPrint,
    '/worksheets/:id': WorksheetDetailPage,
    '/worksheets/:wsId/plan-tasks/:planTaskId': PlanTaskDetailPage,
    '/estimates/:id/wizard': EstimateWizardPage,
    '/estimates/:id': EstimateDetailPage,
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
    '/email': EmailInboxPage,
    '/email/:id/create-job': EmailCreateJobPage,
    '/email/:id/associate': EmailAssociatePage,
    '/email/:id': EmailDetailPage,
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
  }
</style>
