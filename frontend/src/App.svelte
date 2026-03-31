<script>
  import Router from 'svelte-spa-router';
  import Sidebar from './components/Sidebar.svelte';
  import { user, authChecked, checkAuth } from './stores/auth.js';
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
  import SettingsPage from './routes/SettingsPage.svelte';
  import InvoiceDetailPage from './routes/invoices/InvoiceDetailPage.svelte';
  import JobBoardPage from './routes/jobs/JobBoardPage.svelte';
  import ProfilePage from './routes/ProfilePage.svelte';

  const routes = {
    '/': Home,
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
    '/invoices/:id': InvoiceDetailPage,
    '/settings': SettingsPage,
    '/profile': ProfilePage,
  };

  let sidebarOpen = $state(false);

  checkAuth();
</script>

{#if !$authChecked}
  <p>Loading...</p>
{:else if !$user}
  <LoginPage />
{:else}
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
