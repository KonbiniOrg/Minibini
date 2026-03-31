<script>
  import Router from 'svelte-spa-router';
  import Nav from './components/Nav.svelte';
  import { viewMode, toggleViewMode } from './stores/viewMode.js';
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
  };

  checkAuth();
</script>

{#if !$authChecked}
  <p>Loading...</p>
{:else if !$user}
  <LoginPage />
{:else}
  <!-- Site header placeholder — will contain navigation and user info -->
  <div class="site-header-placeholder">
    <Nav />
  </div>
  <Router {routes} />
  <hr>
  <footer>
    <a href="#" onclick={(e) => { e.preventDefault(); toggleViewMode(); }}>
      Switch to {$viewMode === 'full' ? 'lite' : 'full'} view
    </a>
  </footer>
{/if}
