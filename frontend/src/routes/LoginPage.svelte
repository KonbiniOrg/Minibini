<script>
  import { login } from '../stores/auth.js';

  let username = '';
  let password = '';
  let error = '';

  async function handleSubmit() {
    error = '';
    try {
      await login(username, password);
    } catch (e) {
      error = e.message || 'Login failed';
    }
  }
</script>

<h2>Log In</h2>
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
