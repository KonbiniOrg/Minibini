<script>
  import { link } from 'svelte-spa-router';
</script>

<nav>
  <a href="/" use:link>Home</a>
  | <a href="/contacts" use:link>Contacts</a>
  | <a href="/businesses" use:link>Businesses</a>
  | <a href="/jobs" use:link>Jobs</a>
</nav>
<hr>
