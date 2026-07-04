<script>
  import { push } from 'svelte-spa-router';
  import { login } from '../stores/auth.js';

  let { notice = '' } = $props();

  let username = '';
  let password = '';
  let error = '';

  async function handleSubmit() {
    error = '';
    try {
      await login(username, password);
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
