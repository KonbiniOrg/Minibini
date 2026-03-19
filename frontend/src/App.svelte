<script>
  import Router from 'svelte-spa-router';
  import Nav from './components/Nav.svelte';
  import { viewMode, toggleViewMode } from './stores/viewMode.js';
  import Home from './routes/Home.svelte';
  import ContactListPage from './routes/contacts/ContactListPage.svelte';
  import ContactDetailPage from './routes/contacts/ContactDetailPage.svelte';
  import ContactFormPage from './routes/contacts/ContactFormPage.svelte';
  import BusinessListPage from './routes/contacts/BusinessListPage.svelte';
  import BusinessDetailPage from './routes/contacts/BusinessDetailPage.svelte';
  import BusinessFormPage from './routes/contacts/BusinessFormPage.svelte';
  import JobListPage from './routes/jobs/JobListPage.svelte';
  import JobDetailPage from './routes/jobs/JobDetailPage.svelte';

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
    '/jobs/:id': JobDetailPage,
  };
</script>
<Nav />
<Router {routes} />
<hr>
<footer>
  <a href="#" onclick={(e) => { e.preventDefault(); toggleViewMode(); }}>
    Switch to {$viewMode === 'full' ? 'lite' : 'full'} view
  </a>
</footer>
