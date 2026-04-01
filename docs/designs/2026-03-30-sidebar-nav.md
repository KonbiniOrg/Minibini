# Sidebar Navigation Design

Replaces the existing horizontal nav bar (`Nav.svelte`) and the job board's custom slide-down nav with a consistent hamburger-triggered sidebar across all Svelte SPA pages. Django server-rendered pages are unchanged.

## Hamburger Icon

- Always visible, pinned to the top-left corner of the viewport (`position: fixed`)
- Dark background (#222), white bars, `border-bottom-right-radius: 6px`
- 44x44px hit target
- `z-index` above the sidebar so it remains visible when the sidebar is open

## Sidebar

- Slides out from the left edge on hover over the hamburger icon
- 120px wide, dark background (#222), full viewport height
- Push behavior: page content shifts right via `margin-left` transition when sidebar opens
  - To switch to overlay behavior, remove the `margin-left` transition on the page content wrapper — the sidebar markup and animation stay the same
- Slide animation: `transform: translateX(-100%)` → `translateX(0)`, 0.25s ease
- Stays open as long as the user's mouse is over the sidebar or the hamburger
- Closes with a ~300ms delay when the mouse leaves (prevents accidental dismissal)

## Link Structure

All authenticated users see:

```
Jobs
Contacts
Email
Purchasing          ← can_view_financials OR can_manage_financials
My Tasks
─── Admin ──────    ← label hidden if user has none of the permissions below
Manage              ← can_manage_time OR can_approve_expenses
Settings            ← can_manage_config
━━━━━━━━━━━━━━━━
<username> Profile  ← always visible, links to user profile page (not yet built)
Logout
```

- "Admin" section label only appears if the user has at least one permission that reveals an item beneath it
- Logout and `<username> Profile` are pinned to the bottom of the sidebar, separated by a top border
- `<username>` is the logged-in user's display name (e.g., "dev_user Profile")

## Permission Mapping

| Link | Required Permission |
|------|-------------------|
| Jobs | IsAuthenticated |
| Contacts | IsAuthenticated |
| Email | IsAuthenticated |
| Purchasing | `can_view_financials` OR `can_manage_financials` |
| My Tasks | IsAuthenticated |
| Manage | `can_manage_time` OR `can_approve_expenses` |
| Settings | `can_manage_config` |
| `<username>` Profile | IsAuthenticated |
| Logout | IsAuthenticated |

## What It Replaces

- `frontend/src/components/Nav.svelte` — the current horizontal nav bar rendered in `App.svelte`
- The `site-header-placeholder` wrapper in `App.svelte`
- The custom slide-down nav in `JobBoardPage.svelte` (the `onMount` that hides the header, the `handleMouseMove` hover detection, and the `.slide-nav` / `.board-nav` markup)
- The view mode toggle link in the `App.svelte` footer — relocated to the user profile page

## Styling

- Background: #222, link text: #ddd, hover background: #333, hover text: #fff
- Font size: 15px, padding: 9px 12px per link
- Section label ("Admin"): 10px uppercase, #777, with top padding to separate from links above
- Bottom area (profile + logout) separated by 1px solid #444 border

## Scope

- All Svelte SPA pages get the sidebar
- The job board page no longer needs its own nav — it uses the same sidebar
- Django server-rendered pages (`base.html`) are not changed
- The user profile page linked from `<username> Profile` should be created as a minimal page containing just the view mode toggle (lite/full) for now — it will be built out later with password change, etc.

## Reference Mockups

Interactive HTML mockups are in `.superpowers/brainstorm/`:
- `sidebar-overlay.html` — overlay behavior
- `sidebar-push.html` — push behavior (chosen approach)
