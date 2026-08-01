<script>
  import { push } from 'svelte-spa-router';
  import { login } from '../stores/auth.js';
  import { reloadPage } from '../lib/navigation.js';

  let { notice = '' } = $props();

  let username = $state('');
  let password = $state('');
  let error = $state('');

  // True when the hash names a page to go back to — i.e. anything but an
  // absent or root route. Querystring stripped: '#/?tab=shifts' is still Home.
  function hashNamesAPage() {
    const path = window.location.hash.replace(/^#/, '').split('?')[0];
    return path !== '' && path !== '/';
  }

  async function handleSubmit() {
    error = '';
    try {
      const data = await login(username, password);
      // A user's very first login ever lands on the Help tab (the tutorial).
      if (data.first_login) {
        push('/help');
        return;
      }
      // The hash is untouched by a session expiry (App.svelte swaps this page
      // in over the top) and by a deep link opened while logged out — so a
      // non-root hash names the page the user actually wants. Reload rather
      // than re-render: every store and every page fetch rebuilds from
      // scratch, so nothing survives from the dead session. A deliberate
      // logout can't land here — it sends the hash back to '/' on its way out.
      if (hashNamesAPage()) {
        reloadPage();
        return;
      }
      push('/');
    } catch (e) {
      error = e.message || 'Login failed';
    }
  }
</script>

<h2>Log In</h2>
{#if notice}
  <p class="notice">{notice}</p>
{/if}
<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
  <p>
    <label for="username"><strong>Username</strong></label><br>
    <input id="username" type="text" bind:value={username} required>
  </p>
  <p>
    <label for="password"><strong>Password</strong></label><br>
    <input id="password" type="password" bind:value={password} required>
  </p>
  {#if error}
    <p style="color: red;">{error}</p>
  {/if}
  <p><button type="submit">Log In</button></p>
</form>

<style>
  .notice {
    color: #854d0e;
    background: #fef9c3;
    border: 1px solid #ca8a04;
    padding: 8px 12px;
    border-radius: 4px;
    max-width: 320px;
  }
</style>
