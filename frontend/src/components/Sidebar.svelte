<script>
  import { link } from 'svelte-spa-router';
  import { user, logout } from '../stores/auth.js';

  let { open = $bindable(false) } = $props();
  let closeTimeout = $state(null);

  function openSidebar() {
    clearTimeout(closeTimeout);
    open = true;
  }

  function scheduleClose() {
    closeTimeout = setTimeout(() => {
      open = false;
    }, 300);
  }

  async function handleLogout() {
    await logout();
  }

  function hasPerm(perm) {
    return $user?.permissions?.includes(perm) ?? false;
  }

  let showPurchasing = $derived(hasPerm('can_view_financials') || hasPerm('can_manage_financials'));
  let showManage = $derived(hasPerm('can_manage_time') || hasPerm('can_approve_expenses'));
  let showSettings = $derived(hasPerm('can_manage_config'));
  let showAdminLabel = $derived(showManage || showSettings);
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="hamburger"
  onmouseenter={openSidebar}
  onmouseleave={scheduleClose}
>
  <span></span>
  <span></span>
  <span></span>
</div>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="sidebar" class:open={open}
  onmouseenter={openSidebar}
  onmouseleave={scheduleClose}
>
  <nav>
    <a href="/jobs/board" use:link>Jobs</a>
    <a href="/contacts" use:link>Contacts</a>
    <a href="/email" use:link>Email</a>
    {#if showPurchasing}
      <a href="/purchasing" use:link>Purchasing</a>
    {/if}
    <a href="/my-tasks" use:link>My Tasks</a>
    {#if showAdminLabel}
      <div class="section-label">Admin</div>
    {/if}
    {#if showManage}
      <a href="/manage" use:link>Manage</a>
    {/if}
    {#if showSettings}
      <a href="/settings" use:link>Settings</a>
    {/if}
    <div class="spacer"></div>
    <div class="bottom-area">
      {#if $user}
        <a href="/profile" use:link>{$user.username}</a>
        <a href="#" class="nav-link" onclick={(e) => { e.preventDefault(); handleLogout(); }}>Logout</a>
      {/if}
    </div>
  </nav>
</div>

<style>
  .hamburger {
    position: fixed;
    top: 0;
    left: 0;
    z-index: 1000;
    width: 44px;
    height: 44px;
    background: #1a3344;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    gap: 5px;
    border-bottom-right-radius: 6px;
  }
  .hamburger span {
    display: block;
    width: 22px;
    height: 2px;
    background: #fff;
  }

  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    width: 120px;
    height: 100vh;
    box-sizing: border-box;
    background: #1a3344;
    color: #eee;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    z-index: 999;
    display: flex;
    flex-direction: column;
    padding-top: 54px;
  }
  .sidebar.open {
    transform: translateX(0);
  }

  nav {
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 8px 0;
    width: 120px;
  }

  a, .nav-link {
    display: block;
    padding: 9px 12px;
    color: #ddd;
    text-decoration: none;
    font-size: 15px;
    border: none;
    background: none;
    text-align: left;
    cursor: pointer;
    width: 100%;
    font-family: inherit;
    white-space: nowrap;
    overflow: hidden;
    box-sizing: border-box;
  }
  a:hover, .nav-link:hover {
    background: #264a5e;
    color: #fff;
    box-shadow: 8px 0 0 #264a5e;
  }

  .section-label {
    padding: 14px 12px 4px;
    font-size: 10px;
    text-transform: uppercase;
    color: #6a9aab;
    letter-spacing: 0.5px;
  }

  .spacer { flex: 1; }

  .bottom-area {
    border-top: 1px solid #2d5468;
    padding: 4px 0;
  }
</style>
