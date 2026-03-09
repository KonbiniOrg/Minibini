<script>
  import Router from 'svelte-spa-router';
  import Nav from './components/Nav.svelte';
  import Home from './routes/Home.svelte';

  const routes = {
    '/': Home,
  };
</script>

<h1>Minibini</h1>
<Nav />
<Router {routes} />
