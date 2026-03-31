# Sidebar Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the horizontal nav bar and job board slide-down nav with a consistent hamburger-triggered sidebar across all Svelte SPA pages.

**Architecture:** A new `Sidebar.svelte` component handles the hamburger icon, sidebar panel, hover logic, permission-based link visibility, and push behavior. `App.svelte` swaps out `Nav.svelte` for `Sidebar.svelte` and wraps the router in a content div that shifts on sidebar open. `JobBoardPage.svelte` drops its custom nav. A new `ProfilePage.svelte` route holds the view mode toggle.

**Tech Stack:** Svelte 5 (runes), svelte-spa-router, existing auth store (`$user.permissions`)

**Design spec:** `docs/designs/2026-03-30-sidebar-nav.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/components/Sidebar.svelte` | Create | Hamburger icon, sidebar panel, hover open/close, permission-gated links, logout |
| `frontend/src/routes/ProfilePage.svelte` | Create | Minimal user profile page with view mode toggle |
| `frontend/src/App.svelte` | Modify | Replace Nav with Sidebar, wrap Router in pushable content div, add profile route, remove footer toggle |
| `frontend/src/routes/jobs/JobBoardPage.svelte` | Modify | Remove custom nav (onMount header hide, slide-nav markup, handleMouseMove) |
| `frontend/src/components/Nav.svelte` | Delete | No longer used |

---

### Task 1: Create Sidebar.svelte

**Files:**
- Create: `frontend/src/components/Sidebar.svelte`

- [ ] **Step 1: Create the Sidebar component**

```svelte
<script>
  import { link } from 'svelte-spa-router';
  import { user, logout } from '../stores/auth.js';

  let sidebarOpen = $state(false);
  let closeTimeout = $state(null);

  function openSidebar() {
    clearTimeout(closeTimeout);
    sidebarOpen = true;
  }

  function scheduleClose() {
    closeTimeout = setTimeout(() => {
      sidebarOpen = false;
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
<div class="sidebar" class:open={sidebarOpen}
  onmouseenter={openSidebar}
  onmouseleave={scheduleClose}
>
  <nav>
    <a href="/jobs" use:link>Jobs</a>
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
        <a href="/profile" use:link>{$user.username} Profile</a>
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
    background: #222;
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
    background: #222;
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
  }
  a:hover, .nav-link:hover {
    background: #333;
    color: #fff;
  }

  .section-label {
    padding: 14px 12px 4px;
    font-size: 10px;
    text-transform: uppercase;
    color: #777;
    letter-spacing: 0.5px;
  }

  .spacer { flex: 1; }

  .bottom-area {
    border-top: 1px solid #444;
    padding: 4px 0;
  }
</style>
```

- [ ] **Step 2: Verify it renders without errors**

Start the dev server if not running, then temporarily import Sidebar in App.svelte alongside Nav to confirm it loads:

```bash
cd frontend && npm run dev
```

Open `http://localhost:9000` and check browser console for errors. Revert any temporary import after confirming.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Sidebar.svelte
git commit -m "feat: add Sidebar component with hamburger menu and permission-gated links"
```

---

### Task 2: Create ProfilePage.svelte

**Files:**
- Create: `frontend/src/routes/ProfilePage.svelte`

- [ ] **Step 1: Create the minimal profile page with view mode toggle**

```svelte
<script>
  import { user } from '../stores/auth.js';
  import { viewMode, toggleViewMode } from '../stores/viewMode.js';
</script>

<h2>{$user?.username} Profile</h2>

<p>
  View mode: <strong>{$viewMode}</strong>
  — <a href="#" onclick={(e) => { e.preventDefault(); toggleViewMode(); }}>
    Switch to {$viewMode === 'full' ? 'lite' : 'full'} view
  </a>
</p>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/routes/ProfilePage.svelte
git commit -m "feat: add minimal ProfilePage with view mode toggle"
```

---

### Task 3: Update App.svelte

**Files:**
- Modify: `frontend/src/App.svelte`

This is the integration step. We replace Nav with Sidebar, wrap the Router in a content div that shifts when the sidebar opens, add the `/profile` route, and remove the footer view mode toggle.

- [ ] **Step 1: Replace App.svelte contents**

The new `App.svelte`:

```svelte
<script>
  import Router from 'svelte-spa-router';
  import Sidebar from './components/Sidebar.svelte';
  import { user, authChecked, checkAuth } from './stores/auth.js';
  import LoginPage from './routes/LoginPage.svelte';
  import Home from './routes/Home.svelte';
  import ContactListPage from './routes/contacts/ContactListPage.svelte';
  import ContactDetailPage from './routes/contacts/ContactDetailPage.svelte';
  import ContactFormPage from './routes/contacts/ContactFormPage.svelte';
  import BusinessListPage from './routes/contacts/BusinessListPage.svelte';
  import BusinessDetailPage from './routes/contacts/BusinessDetailPage.svelte';
  import BusinessFormPage from './routes/contacts/BusinessFormPage.svelte';
  import JobListPage from './routes/jobs/JobListPage.svelte';
  import JobDetailPage from './routes/jobs/JobDetailPage.svelte';
  import SettingsPage from './routes/SettingsPage.svelte';
  import InvoiceDetailPage from './routes/invoices/InvoiceDetailPage.svelte';
  import JobBoardPage from './routes/jobs/JobBoardPage.svelte';
  import ProfilePage from './routes/ProfilePage.svelte';

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
    '/jobs/board': JobBoardPage,
    '/jobs/:id': JobDetailPage,
    '/invoices/:id': InvoiceDetailPage,
    '/settings': SettingsPage,
    '/profile': ProfilePage,
  };

  checkAuth();
</script>

{#if !$authChecked}
  <p>Loading...</p>
{:else if !$user}
  <LoginPage />
{:else}
  <Sidebar />
  <!--
    Push behavior: the sidebar sets margin-left on this wrapper when open.
    To switch to overlay behavior, remove the .page-content class and its
    CSS below — the sidebar will overlay the page instead of pushing it.
  -->
  <div class="page-content">
    <Router {routes} />
  </div>
{/if}

<style>
  .page-content {
    transition: margin-left 0.25s ease;
    padding-top: 8px;
  }
</style>
```

Note: The push behavior requires the Sidebar component to toggle a class on `.page-content`. We need to make the sidebar communicate with the page content wrapper. There are two clean approaches: (a) bind a prop, or (b) use a store. Let's use a simple exported binding from Sidebar.

- [ ] **Step 2: Add sidebarOpen binding to Sidebar.svelte**

In `frontend/src/components/Sidebar.svelte`, change the `sidebarOpen` declaration to use `$bindable()` so the parent can read it:

At the top of the `<script>` block, add an `open` prop:

```svelte
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
```

And update the template to use `open` instead of `sidebarOpen`:

```svelte
<div class="sidebar" class:open={open}
```

- [ ] **Step 3: Update App.svelte to use the binding for push behavior**

Update the `App.svelte` authenticated block:

```svelte
{:else}
  <Sidebar bind:open={sidebarOpen} />
  <!--
    Push behavior: margin-left shifts content when sidebar opens.
    To switch to overlay: remove the style:margin-left line below.
  -->
  <div class="page-content" style:margin-left={sidebarOpen ? '120px' : '0'}>
    <Router {routes} />
  </div>
{/if}
```

And add `sidebarOpen` to the script block:

```svelte
<script>
  // ... existing imports ...
  let sidebarOpen = $state(false);
  // ... rest of script ...
</script>
```

- [ ] **Step 4: Verify in browser**

Open `http://localhost:9000`. Confirm:
- Hamburger icon visible top-left
- Hover opens sidebar, content pushes right
- Mouse leave closes sidebar after ~300ms delay
- Links render correctly based on user permissions
- Old horizontal nav is gone
- Footer view mode toggle is gone
- `http://localhost:9000/#/profile` shows the profile page with view mode toggle

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.svelte frontend/src/components/Sidebar.svelte frontend/src/routes/ProfilePage.svelte
git commit -m "feat: integrate sidebar nav into App, add profile route, remove old nav and footer toggle"
```

---

### Task 4: Clean up JobBoardPage.svelte

**Files:**
- Modify: `frontend/src/routes/jobs/JobBoardPage.svelte`

The job board currently hides the app-level nav on mount and has its own slide-down nav. Since the sidebar now works everywhere, all of that custom nav code can go.

- [ ] **Step 1: Remove custom nav code from JobBoardPage.svelte**

Remove these pieces:

1. The `navVisible` state variable (line 15): `let navVisible = $state(false);`
2. The `onMount` block (lines 38-51) that hides the header/footer
3. The `handleMouseMove` function (lines 53-55)
4. The `<svelte:window onmousemove={handleMouseMove} />` element (line 58)
5. The entire `.slide-nav` / `.board-nav` markup block (lines 61-73)
6. The `.slide-nav`, `.slide-nav.visible`, `.board-nav`, `.board-nav a`, `.board-nav a:hover`, and `.sep` CSS rules (lines 104-131)
7. The `import { onMount } from 'svelte';` if no longer used

The remaining component should just be the board data loading, permission check, and board layout.

After cleanup, the script block should look like:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { user } from '../../stores/auth.js';
  import PipelineColumn from '../../components/board/PipelineColumn.svelte';
  import ApprovedArea from '../../components/board/ApprovedArea.svelte';
  import ClosedColumn from '../../components/board/ClosedColumn.svelte';
  import ResizeHandle from '../../components/board/ResizeHandle.svelte';

  let boardData = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let pipelineWidth = $state(270);
  let closedWidth = $state(270);

  async function loadBoard() {
    loading = true;
    error = null;
    try {
      boardData = await api.get('/api/jobs/board/');
    } catch (e) {
      error = e.message || 'Failed to load board';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    loadBoard();
  });

  function canManageJobs() {
    return $user?.permissions?.includes('can_manage_jobs');
  }
</script>
```

And the template starts directly with `<div class="board-page">` — no `<svelte:window>` or `.slide-nav` block.

- [ ] **Step 2: Verify the job board in browser**

Open `http://localhost:9000/#/jobs/board`. Confirm:
- The board renders normally
- The hamburger sidebar works (same as all other pages)
- No console errors
- No leftover slide-down nav behavior

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/jobs/JobBoardPage.svelte
git commit -m "refactor: remove custom nav from JobBoardPage, now uses app-level sidebar"
```

---

### Task 5: Delete Nav.svelte

**Files:**
- Delete: `frontend/src/components/Nav.svelte`

- [ ] **Step 1: Verify Nav.svelte is no longer imported anywhere**

```bash
cd /Users/drshiny/Documents/konbini/Minibini && grep -r "Nav.svelte\|from.*Nav\|import Nav" frontend/src/
```

Should return no results (App.svelte now imports Sidebar instead).

- [ ] **Step 2: Delete the file**

```bash
rm frontend/src/components/Nav.svelte
```

- [ ] **Step 3: Verify the app still works**

Open `http://localhost:9000` and navigate between a few pages. No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Nav.svelte
git commit -m "chore: delete Nav.svelte, replaced by Sidebar"
```

---

### Task 6: Final verification

- [ ] **Step 1: Test all permission combinations**

Log in as different user roles and verify sidebar link visibility:

| Role | Expected links |
|------|---------------|
| Worker (no perms) | Jobs, Contacts, Email, My Tasks, Profile, Logout |
| Admin (`can_manage_jobs`, `can_view_financials`) | + Purchasing |
| Bookkeeper (`can_view_financials`, `can_manage_financials`, `can_approve_expenses`) | + Purchasing, Admin label, Manage |
| Manager (all except `can_manage_config`) | + Purchasing, Admin label, Manage |
| Owner (all perms) | + Purchasing, Admin label, Manage, Settings |

- [ ] **Step 2: Test the job board page**

Navigate to `http://localhost:9000/#/jobs/board`. Confirm the sidebar works identically to other pages — no special behavior, no leftover custom nav.

- [ ] **Step 3: Test the profile page**

Navigate to `http://localhost:9000/#/profile`. Confirm the view mode toggle works and persists across page reloads.

- [ ] **Step 4: Test sidebar push behavior**

On any page, hover the hamburger. Confirm:
- Sidebar slides out from left (0.25s)
- Page content shifts right simultaneously
- Moving mouse to sidebar keeps it open
- Moving mouse away closes after ~300ms
- Hamburger stays in top-left corner throughout
