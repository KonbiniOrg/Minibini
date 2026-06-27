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
  import DuplicateJobPage from './routes/jobs/DuplicateJobPage.svelte';
  import TaskDetailPage from './routes/jobs/TaskDetailPage.svelte';
  import SettingsPage from './routes/SettingsPage.svelte';
  import InventoryListPage from './routes/inventory/InventoryListPage.svelte';
  import InvoiceDetailPage from './routes/invoices/InvoiceDetailPage.svelte';
  import InvoiceListPage from './routes/invoices/InvoiceListPage.svelte';
  import InvoiceSendPage from './routes/invoices/InvoiceSendPage.svelte';
  import InvoiceWizardPage from './routes/invoices/InvoiceWizardPage.svelte';
  import BillListPage from './routes/bills/BillListPage.svelte';
  import BillFormPage from './routes/bills/BillFormPage.svelte';
  import BillDetailPage from './routes/bills/BillDetailPage.svelte';
  import JobBoardPage from './routes/jobs/JobBoardPage.svelte';
  import SchedulePage from './routes/schedule/SchedulePage.svelte';
  import ProfilePage from './routes/ProfilePage.svelte';
  import SearchPage from './routes/Search.svelte';
  import WorksheetDetailPage from './routes/worksheets/WorksheetDetailPage.svelte';
  import PlanTaskDetailPage from './routes/worksheets/PlanTaskDetailPage.svelte';
  import EstimateDetailPage from './routes/estimates/EstimateDetailPage.svelte';
  import EstimateSendPage from './routes/estimates/EstimateSendPage.svelte';
  import EstimateWizardPage from './routes/estimates/EstimateWizardPage.svelte';
  import JobTaskListPage from './routes/jobs/JobTaskListPage.svelte';
  import JobShipmentsPage from './routes/jobs/JobShipmentsPage.svelte';
  import JobHistoryPage from './routes/jobs/JobHistoryPage.svelte';
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
    '/jobs/:id/edit': JobEditPage,
    '/jobs/:id/duplicate': DuplicateJobPage,
    '/jobs/:id/tasklist': JobTaskListPage,
    '/jobs/:id/history': JobHistoryPage,
    '/jobs/:jobId/shipments': JobShipmentsPage,
    '/jobs/:jobId/tasks/:taskId': TaskDetailPage,
    '/shipments/:sid/print': PackingListPrint,
    '/worksheets/:id': WorksheetDetailPage,
    '/worksheets/:wsId/plan-tasks/:planTaskId': PlanTaskDetailPage,
    '/estimates/:id/wizard': EstimateWizardPage,
    '/estimates/:id/send': EstimateSendPage,
    '/estimates/:id': EstimateDetailPage,
    '/purchase-orders': PurchaseOrderListPage,
    '/purchase-orders/new': PurchaseOrderFormPage,
    '/purchase-orders/:id/edit': PurchaseOrderFormPage,
    '/purchase-orders/:id/send': PurchaseOrderSendPage,
    '/purchase-orders/:id': PurchaseOrderDetailPage,
    '/invoices': InvoiceListPage,
    '/invoices/:id/wizard': InvoiceWizardPage,
    '/invoices/:id/send': InvoiceSendPage,
    '/invoices/:id': InvoiceDetailPage,
    '/bills': BillListPage,
    '/bills/new': BillFormPage,
    '/bills/:id/edit': BillFormPage,
    '/bills/:id': BillDetailPage,
    '/settings': SettingsPage,
    '/inventory': InventoryListPage,
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
    '/profile': ProfilePage,
    '/change-orders/:id/send': ChangeOrderSendPage,
    '/change-orders/:id': ChangeOrderDetailPage,
  };

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
  <Sidebar />
  <!--
    Overlay behavior: the sidebar is position:fixed at the --z-sidebar tier
    (see the z-index scale in css/app.css), so it slides in on top of the page
    without shifting content.
  -->
  <div class="page-content">
    <Router {routes} />
  </div>
{/if}
