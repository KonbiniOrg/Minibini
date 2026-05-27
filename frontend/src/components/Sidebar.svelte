<script>
  import { link, push } from 'svelte-spa-router';
  import { user, logout } from '../stores/auth.js';
  import { viewMode, toggleViewMode } from '../stores/viewMode.js';

  let { open = $bindable(false) } = $props();
  let closeTimeout = $state(null);

  function openSidebar() {
    clearTimeout(closeTimeout);
    open = true;
  }

  function scheduleClose() {
    if (searchFocused) return;
    closeTimeout = setTimeout(() => {
      if (!searchFocused) open = false;
    }, 300);
  }

  async function handleLogout() {
    await logout();
  }

  function hasPerm(perm) {
    return $user?.permissions?.includes(perm) ?? false;
  }

  let showFinancials = $derived(hasPerm('can_manage_financials'));
  let showAdminLabel = $derived(showFinancials || hasPerm('can_manage_config'));

  let searchQuery = $state('');
  let searchFocused = $state(false);

  function handleSearch(e) {
    e.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;
    searchQuery = '';
    searchFocused = false;
    open = false;
    push(`/search?q=${encodeURIComponent(q)}`);
  }
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
    <a href="/" use:link>Home</a>
    <a href="/jobs/board" use:link>Jobs</a>
    <a href="/schedule" use:link>Schedule</a>
    <a href="/activity" use:link>Activity</a>
    <a href="/contacts" use:link>Contacts</a>
    <a href="/email" use:link>Email</a>
    <a href="/purchase-orders" use:link>Purchasing</a>
    {#if showAdminLabel}
      <div class="section-label">Admin</div>
    {/if}
    {#if showFinancials}
      <a href="/expenses" use:link>Expenses</a>
    {/if}
    {#if hasPerm('can_manage_config')}
      <a href="/users" use:link>Users</a>
    {/if}
    {#if hasPerm('can_manage_config')}
      <a href="/settings" use:link>Settings</a>
    {/if}
    <form class="sidebar-search" onsubmit={handleSearch}>
      <input
        type="search"
        placeholder="Search..."
        bind:value={searchQuery}
        aria-label="Search"
        onfocus={() => searchFocused = true}
        onblur={() => { searchFocused = false; scheduleClose(); }}
      />
    </form>
    <div class="spacer"></div>
    <div class="view-mode-toggle">
      {#if $viewMode === 'full'}
        <span class="active">FULL</span>
        <button class="inactive" onclick={toggleViewMode}>LITE</button>
      {:else}
        <button class="inactive" onclick={toggleViewMode}>FULL</button>
        <span class="active">LITE</span>
      {/if}
    </div>
    <div class="bottom-area">
      {#if $user}
        <a href="/profile" use:link>{$user.username}</a>
        <button class="nav-link" onclick={handleLogout}>Logout</button>
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

  nav a, .nav-link {
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
  nav a:hover, .nav-link:hover {
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

  .sidebar-search {
    padding: 8px 12px;
    margin: 0;
  }
  .sidebar-search input {
    width: 100%;
    box-sizing: border-box;
    background: #264a5e;
    border: 1px solid #3d6a7e;
    color: #eee;
    padding: 5px 7px;
    font-size: 13px;
    border-radius: 3px;
    font-family: inherit;
  }
  .sidebar-search input::placeholder {
    color: #6a9aab;
  }
  .sidebar-search input:focus {
    outline: none;
    border-color: #6a9aab;
  }

  .spacer { flex: 1; }

  .view-mode-toggle {
    display: flex;
    justify-content: space-between;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 0.5px;
  }
  .view-mode-toggle .active,
  nav .view-mode-toggle button.inactive {
    display: inline;
    padding: 0;
    width: auto;
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 0.5px;
    line-height: 1;
    text-decoration: none;
    background: none;
    border: none;
    cursor: pointer;
    font-family: inherit;
  }
  .view-mode-toggle .active {
    color: #fff;
  }
  nav .view-mode-toggle button.inactive {
    color: #6a9aab;
  }
  nav .view-mode-toggle button.inactive:hover {
    color: #aac7d6;
    background: none;
    box-shadow: none;
  }

  .bottom-area {
    border-top: 1px solid #2d5468;
    padding: 4px 0;
  }
</style>
