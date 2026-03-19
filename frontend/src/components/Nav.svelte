<script>
  import { link } from 'svelte-spa-router';
</script>

<nav>
  <a href="/" use:link>HOME</a>
  ◆ <a href="/contacts" use:link>CONTACTS</a>
  ◆ <a href="/businesses" use:link>BUSINESSES</a>
  ◆ <a href="/jobs" use:link>JOBS</a>
</nav>

<style>
  nav {
    border: 1px solid #999;
    border-radius: 8px;
    padding: 0.5em 1em;
    text-align: center;
    width: fit-content;
    margin: 0.5em auto;
  }
</style>

