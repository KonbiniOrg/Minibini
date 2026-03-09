<script>
  import Router from 'svelte-spa-router';
  import Nav from './components/Nav.svelte';
  import Home from './routes/Home.svelte';
  import ContactListPage from './routes/contacts/ContactListPage.svelte';
  import ContactDetailPage from './routes/contacts/ContactDetailPage.svelte';

  const routes = {
    '/': Home,
    '/contacts': ContactListPage,
    '/contacts/:id': ContactDetailPage,
  };
</script>

<h1>Minibini</h1>
<Nav />
<Router {routes} />
