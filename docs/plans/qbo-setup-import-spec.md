# Spec: Gradual setup + QBO data import

Branch: `feature/qbo`. Third of the three QBO-deepening changes (after
QBO-primary invoicing and Bill removal). Grew during design into the broader
**new-tenant setup experience**: seeded defaults, per-area gating, per-tenant
email config, and a QBO snapshot import distributed through the app's
existing surfaces. No modal wizard.

## Context and boundaries

- A tenant always has a QBO connection (assumption held for now; every screen
  reads the snapshot, so a no-QBO manual path remains *possible* later —
  keep it as a design factor, do not build it).
- Tenant spool-up/signup (which creates the first superuser) is deferred;
  this work begins at that superuser's first login.
- Multi-tenant DB is deferred; DB credentials and the Intuit **app**
  credentials (`QBO_CLIENT_ID`/`SECRET`/`REDIRECT_URI`/`ENVIRONMENT` — these
  identify the developer-registered application, shared across tenants;
  verified) stay in the deployment environment. Per-tenant QBO state is
  already in `qbo_connection`.
- Ongoing QBO↔konbini sync is NOT this feature. The import is one-directional
  (QBO → konbini) with per-row user confirmation; "update" rows (below) are
  as far as change-handling goes.

## Part 1 — Seeded defaults (data migration)

A data migration seeds, when absent (idempotent, every environment):

- **AppState**: `job_counter`, `po_counter` = `'0'`. (Fixes the fresh-DB trap:
  nothing but fixtures creates these today, so a migrate-only DB cannot
  create a Job — `apps/core/services.py:166-172`.)
- **Configuration**: `job_number_sequence`, `po_number_sequence` (current
  default patterns), `units_list` (the built-in `DEFAULT_UNITS`).

"Reviewing defaults" is not a wizard step — it's Settings, reachable from
day one, with Home-Help pointing at it.

Also fold in two adjacent bugfixes surfaced by the config audit:
- `GET /api/settings/units/` 500s when `units_list` is absent
  (`apps/api/templates_config/views.py:280`) — guard with the same
  `DEFAULT_UNITS` fallback the rest of the app uses. (Seeding makes it
  unreachable, but the endpoint shouldn't be able to 500.)
- `scripts/seed_data.sh` — DELETED (RM, 2026-07-23): the curl-based seeding
  approach was superseded by the nealsdata converter; its counter PATCH was
  also silently broken (wrote Configuration, not AppState).

## Part 2 — Per-tenant email settings (Settings → Email tab)

- New Configuration keys for the tenant's mail account: `email_imap_server`,
  `email_address`, `email_password`, `email_smtp_host`, `email_smtp_port`
  (mirroring the current env variables; one account drives both IMAP and
  SMTP today, and that stays). Same trust level as the QBO tokens already
  stored in the DB.
- `EmailService` (IMAP) and outbound SMTP read **DB-first, env fallback** so
  existing deployments keep working unchanged.
- New **Settings → Email** tab: the credential form + a "verify connection"
  button (attempts IMAP login and SMTP handshake, reports each).
- Optionally split the email boilerplate (subject/body template keys) out of
  wherever it lives today into a **Settings → Templates** tab. Cosmetic
  reorganization; keep if cheap.

## Part 3 — Gating (gradual setup)

**Gates are derived, the flag controls the mode.**

- `GET /api/setup/status` (IsAuthenticated) returns, per gated area:
  `{available: bool, message: str}` plus the global `setup_complete` flag and
  last-pull metadata. Single source of truth; the sidebar and Home Help both
  consume it. Messages name the unlock path, e.g. "Add your email service
  configuration on Settings → Email".
- Gate predicates (live queries, cheap):
  | Area | Available when |
  |---|---|
  | Email | email settings configured (DB or env) |
  | Catalog | ≥1 AccountingCategory AND ≥1 RateScheme |
  | Contacts & Businesses | always |
  | Jobs (board/list) | ≥1 Contact |
  | Estimates / Worksheets | Jobs available |
  | Invoices | QBO connected |
  | Purchase Orders | ≥1 Business |
  | Expenses | always (company-paid already has its own inline guard) |
  | Schedule / Search / Activity / Home / Users / Settings | always |
- **While `setup_complete` is unset**: unavailable areas render greyed in the
  sidebar with hovertext (`title` attr / tooltip) from the status message;
  their routes redirect to Home. Home's Help content leads with the setup
  checklist (driven by the same endpoint).
- **`setup_complete`** (Configuration key): auto-set by the status endpoint
  the first time every gate passes. Once set, gating retires permanently —
  areas stay reachable regardless of later data deletion, and the app relies
  on its normal per-action errors. (No re-locking.) Manual override possible
  by editing the key; no UI for that.

## Part 4 — QBO snapshot pull

- Button **"Pull current QBO settings"** in Settings → Accounting → the
  existing QuickBooks Online section, with the **last-pull timestamp
  displayed beside it**. Requires `can_manage_config` + active connection.
- `POST /api/qbo/import/pull` fetches in one sweep: sellable Items (Service /
  NonInventory / Inventory types, with `IncomeAccountRef`, `ExpenseAccountRef`
  where two-sided, UnitPrice, descriptions, tax defaults), income accounts,
  expense+COGS accounts, Customers, Vendors, Terms. Stored as one JSON blob
  in Configuration (`qbo_import_snapshot`) with `fetched_at` inside.
  MySQL `longtext` — size is a non-issue.
- The pull response includes a **diff summary** against current konbini data
  ("214 items, 156 customers …; N new suggestions / no new suggestions"),
  shown at the button. QBO Inventory-type items are pulled and offered as
  inventory items (konbini remains the stock authority; their QBO quantity
  tracking is ignored).
- Re-pull replaces the snapshot. No other state: **no discard memory** —
  suggestions are recomputed live from snapshot vs database every time a
  panel renders, so discarding is just unchecking (or dismissing), and a
  re-pull re-offers everything not yet imported. Changing your mind = pull
  again.

## Part 5 — Suggestion panels (the distributed import)

A shared panel component embedded in four existing surfaces. A panel renders
iff the live diff for its kind is non-empty (or immediately after a pull, to
show the summary; dismissible; naturally gone on re-navigation when empty).

Row states, computed by `qbo_id` match:
- **new** (not in konbini): unchecked by default for judgment kinds
  (categories), checked for mirror kinds (customers/vendors/terms/items);
  action = create.
- **imported, unchanged**: shown checked and inert ("imported").
- **imported, changed in QBO**: checked, action = **update** (field
  overwrite on commit; see ServiceItem exception below).
- Unchecking any row skips it. Commit button applies checked creates/updates
  via one service call per panel; recompute empties the panel.

### 5a. Categories — inside Settings → Accounting Categories

- Candidates derived by clustering the snapshot's sellable Items by
  `IncomeAccountRef`; income accounts with no items appear as additional
  keep/discard candidates (flagged "no QBO item mapped yet" — such a
  category pushes uncatalogued lines with no ItemRef and cannot lazy-mint
  until an Item is mapped later).
- Candidate fields: name (from income account), code (auto-slug, editable),
  taxable (majority of member items' tax defaults), member count.
- Per-candidate pulldowns: **fallback Item** (`qbo_item_id`) from the
  cluster's members, defaulted to a plausible member; **expense account**
  (`qbo_expense_account_id`) from the snapshot's expense/COGS accounts,
  pre-filled by majority `ExpenseAccountRef` of two-sided member items,
  else blank.
- Item-Category (`Type=Category`) rows in QBO are ignored entirely.
- Categories must be committed before item suggestions can be committed
  (items need category FKs); the panels' gating order enforces this
  naturally (Catalog is unreachable until a category and scheme exist).

### 5b. Rate schemes — inside RateSchemeManager (Catalog area)

- One suggested RateScheme per snapshot Service item: name from the item,
  `rate = UnitPrice`, algorithm defaulted `entered_qty`, unit label `'ea'`,
  category = the item's income-account cluster's committed kAC.
- Review table **grouped by price** so shared-rate patterns are visible;
  per-group algorithm/unit override (e.g. mark a group hourly →
  `elapsed_time`/'hours'); per-group opt-in **collapse** onto one shared
  scheme (user names it). Default is one scheme per service (Option A);
  collapse is a gesture, never automatic.

### 5c. Catalog items — inside the Catalog tabs

- Service items → kServiceItems bound to their 5b schemes. NonInventory (and
  QBO-Inventory) items → kInventoryItems: code from Name (uniquified),
  description, `selling_price = UnitPrice`, `purchase_price = PurchaseCost`
  when two-sided, units `'none'`, category from cluster, `qbo_id` set — so
  imported items and lazily-minted ones converge on the same field.
- "Update" rows: InventoryItem price/description = field overwrite;
  **ServiceItem price change routes through RateScheme supersession**
  (existing machinery), never a bare rate edit.
- Client-side search/filter + select all/none — this is the bulk surface
  (hundreds of rows).

### 5d. Customers / vendors / terms — inside Contacts & Businesses

- QBO Terms → `PaymentTerms` (+ new `qbo_id` field on PaymentTerms).
- Customers: with `CompanyName` → Business (+ default Contact from
  Given/Family name + email/phone); without → bare Contact.
  `qbo_customer_id` set. Customer `SalesTermRef` → `Business.terms`.
- Vendors → Business with `qbo_vendor_id` (the field kept through Bill
  removal for exactly this). A same-named Customer+Vendor pair becomes one
  Business with both ids (name-match adopt, mirroring the 6240 helpers'
  philosophy).
- Matching for update rows: `qbo_customer_id`/`qbo_vendor_id`/`qbo_id`.

## Testing

- Backend: snapshot fixtures (canned JSON) drive everything — pull service
  (mocked at `QBOService` boundary), diff/suggestion computation per kind,
  commit services (create/update/skip; ServiceItem supersession path),
  gates endpoint truth table, data-migration idempotency, email-settings
  DB-first fallback, the units-endpoint 500 fix.
- Vitest: sidebar greying + hovertext from mocked setup-status; panel row
  states (new/imported/changed) and commit flows per surface; Settings
  Email tab; pull button + summary + timestamp.
- E2E: a fresh-tenant spec is impractical against the seeded DB (it is by
  definition fully set up), so e2e covers: setup-status endpoint shape via
  API, the pull-button UI with a stubbed error (no QBO connection in e2e —
  asserts the graceful message), and panels' absence on a fully-imported
  DB. Full pull→confirm flows are backend+Vitest territory; note the
  exemption. Manual sandbox verification: one real pull against the dev
  sandbox company end-to-end.

## Out of scope

- Ongoing/scheduled QBO sync; konbini→QBO write-back of any imported kind
  beyond what already exists (customer push, item mint).
- Tenant signup/spool-up; multi-tenant DB; no-QBO setup path.
- Detecting konbini-side edits vs QBO edits (conflict resolution) — update
  rows are last-pull-wins overwrites the user explicitly checks.

## Follow-on doc updates (same session as implementation)

`quickbooks-integration.md` (snapshot pull, import services),
`architecture-and-conventions.md` (gating pattern, setup-status endpoint,
sidebar), `users-and-permissions.md` (new endpoints), `data-constraints.md`
(new config keys, PaymentTerms.qbo_id, seeded defaults),
`contacts-and-businesses.md`, `estimates-and-prices.md` (scheme import /
supersession), `materials-inventory-and-purchasing.md` (item import),
`invoicing-and-expenses.md` (email settings move) — plus CLAUDE.md's
Configuration key list pointer and `frontend/README.md` if panel conventions
warrant it.
