# Flat-Fee Schemes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `docs/plans/2026-08-16-flat-fee-schemes.md`: a fourth
`flat_fee` RateScheme algorithm with item-side amounts, interpretation
fully encapsulated in RateScheme (amounts resolve into `Task.rate` at
stamp time; no consumer ever sees the config JSON's dual use).

**Architecture:** One `ALGORITHM_CHOICES` addition (cosmetic AlterField
migration). Scheme grows three algorithm-owned methods (`resolve_stamp`,
`validate_item_config`, an `effective_rate` branch); `stamp_from_scheme`
delegates; `ServiceItem.clean` validates config via its scheme;
`generate_task` and `add_line_item_from_service` flow through the scheme
methods so flat-fee amounts reach `Task.rate` and line `price` without
any downstream change. SPA: scheme manager gets the algorithm + locked
rate; ServiceItemManager gets an Amount field; pickers show the
effective price. Converter: schemes sourced internally (companion task).

**Tech Stack:** Django 5.2 + DRF, Svelte 5 + Vitest, Playwright.
**Branch:** `feature/estimating` (RM: implement mid-review on this
branch; commit everything here).

## Global Constraints

- **Never write the dev DB** (no migrate/shell/loaddata/ORM writes
  outside `manage.py test`); `makemigrations` allowed and required.
- Django tests: ALWAYS `--noinput`, FOREGROUND with explicit timeout,
  ONE run at a time, judged ONLY by the `Ran N tests`/`OK`/`FAILED`
  summary line; NEVER background/Monitor. Branch already carries
  migrations → final full-suite gate runs WITHOUT `--keepdb`.
- Vitest: `npm run test:run` from frontend/ (never watch). TDD
  everywhere, RED/GREEN evidence in reports.
- Exact constant: `FLAT_FEE = 'flat_fee'`, choices label **'Flat fee'**.
- Encapsulation is the load-bearing requirement: NO consumer outside
  RateScheme may branch on the config JSON's shape. `Task.effective_rate`,
  `copy_active_modifiers`, `validate_active_modifiers`, permission
  gates, bundle math: all UNTOUCHED (reviewers treat any diff there as a
  spec violation).
- No mixing: flat_fee schemes carry an empty own-`modifiers` list; a
  flat-fee item config is exactly one `{label?, amount}` entry (amount >
  0, two decimals); percent keys invalid there.
- Manual flat_fee task (no ServiceItem) stamps rate $0 — documented
  edge, pin it with a test, don't fight it.
- User-visible: "Flat fee"/"Amount" wording — the word "modifier" never
  appears on flat-fee paths. "timeslip" never "blep".
- Converter rules: `tests.test_neals_builders` mandatory;
  nealseed/nealsmall NEVER regenerated or modified; `converted.json` is
  the regenerable artifact.

---

### Task 1: RateScheme — flat_fee constant + scheme-owned interpretation

**Files:**
- Modify: `apps/jobs/models.py` (RateScheme ~560-690; Task.stamp_from_scheme ~440-470)
- Create: migration via `makemigrations jobs` (AlterField choices)
- Test: `tests/test_flat_fee_scheme.py`

**Interfaces (produces):**
- `RateScheme.FLAT_FEE = 'flat_fee'` in `ALGORITHM_CHOICES` as ('flat_fee', 'Flat fee').
- `RateScheme.resolve_stamp(item_config) -> dict` with keys
  `qty_source, rate, unit_label, accounting_category, active_modifiers`:
  existing algorithms return today's values verbatim (qty_source =
  self.algorithm, rate = self.rate, snapshots resolved from keys);
  flat_fee returns `qty_source = RateScheme.ENTERED_QTY` (so
  `Task.get_actual_qty` needs no new branch — verify its qty_source
  values first), `rate = the config's amount` (Decimal, 2dp),
  `active_modifiers = []`. PERCENTAGE still raises ValueError.
- `RateScheme.validate_item_config(entries) -> None|ValidationError`:
  percent algorithms → entries must be key-strings present in
  self.modifiers (today's implicit contract, now explicit); flat_fee →
  exactly one dict entry `{amount: >0, label?: str}`, no percent key.
- `RateScheme.effective_rate(active_modifiers=None)` (~line 633): branch
  flat_fee → the config's amount (entries passed in are the item
  config); other algorithms unchanged.
- `RateScheme.clean()`: flat_fee requires `rate == 0` (message: 'Flat
  fee schemes carry no rate of their own — the amount lives on each
  Service Item.') and `modifiers == []`.
- `Task.stamp_from_scheme(scheme, modifier_keys=None)` — signature
  unchanged; body becomes a delegation to `scheme.resolve_stamp(...)` +
  field assignment + `source_scheme = scheme`. Behavior for existing
  algorithms byte-identical (existing stamping tests must pass
  untouched).

- [ ] TDD: tests first (constant present; resolve_stamp per algorithm
  incl. flat_fee amount→rate and empty modifiers; validate_item_config
  accept/reject matrix; clean() rules; effective_rate flat_fee branch;
  stamp_from_scheme delegation equivalence for entered_qty/elapsed —
  same stamped fields as before; manual-stamp-no-config → rate 0 pin).
  RED → implement → GREEN. Then run the existing scheme/stamping
  modules (grep tests/ for stamp_from_scheme / rate_scheme suites) —
  zero regressions, zero modified assertions.
- [ ] Fresh-DB spot check of the new module (migration added).
- [ ] Commit.

### Task 2: catalog plumbing — ServiceItem validation, generate_task, service-pick pricing

**Files:**
- Modify: `apps/estimates/models.py` (`ServiceItem.clean` ~488;
  `generate_task` ~495-540), `apps/estimates/services.py`
  (`add_line_item_from_service` ~441 — price line already calls
  `scheme.effective_rate(service_item.default_active_modifiers)`, which
  Task 1 made flat_fee-aware: verify, don't rewrite),
  `apps/api/templates_config/serializers.py` (ServiceItemSerializer:
  validate config via scheme on write; expose a read-only
  `display_rate` = scheme.effective_rate(config) so pickers can show
  the real price)
- Test: extend `tests/test_flat_fee_scheme.py` + the service-item API
  module (find it: grep tests/ for service-items)

- [ ] TDD: ServiceItem.clean rejects bad configs via
  `rate_scheme.validate_item_config` (both algorithm families);
  `generate_task` on a flat-fee item stamps Task.rate = amount,
  qty_source entered, active_modifiers [] (route: pass
  `default_active_modifiers` into stamp — confirm generate_task's
  current resolved_modifier_keys path simply forwards to
  stamp_from_scheme and needs no flat_fee branch of its own — the
  encapsulation constraint);
  `add_line_item_from_service` on a flat-fee item prices the line at
  the amount; API create/update of a flat-fee ServiceItem validates;
  `display_rate` correct for both families. RED → GREEN; regressions on
  the touched modules.
- [ ] Commit.

### Task 3: SPA — scheme manager, ServiceItemManager amount field, picker price

**Files:**
- Modify: `frontend/src/components/RateSchemeManager.svelte` ('Flat
  fee' in the algorithm select; when chosen: rate input hidden or
  disabled-at-0 with the spec's one-line explanation; the scheme's own
  modifiers editor hidden), `frontend/src/components/ServiceItemManager.svelte`
  (when the picked scheme is flat_fee: an **Amount** field writing the
  one-entry config — read how the component currently renders
  default_active_modifiers pre-checks and swap that region; the word
  'modifier' never renders on this path),
  `frontend/src/components/PriceListPicker.svelte` (~line 33: price
  from `display_rate` when present, falling back to
  `rate_scheme_detail?.rate`)
- Test: extend the components' Vitest files (find in frontend/tests/)

- [ ] TDD: scheme form flat-fee mode (rate locked, modifiers hidden,
  payload carries rate 0); ServiceItemManager amount field shown for
  flat-fee scheme pick, hidden otherwise, POST body carries the config
  entry; picker row shows display_rate. RED → GREEN; full Vitest suite
  once before commit.
- [ ] Commit.

### Task 4: converter — internal RateScheme sourcing (+ flat_fee ready)

**Files:**
- Modify: `nealsdata/converter/build.py` (~lines 89-140: the pass that
  copies `jobs.ratescheme` records from nealseed), possibly
  `orchestrator.py`
- Test: `tests/test_neals_builders.py`

RM's requirement: the converter must generate its RateSchemes
internally — a `SCHEMES` table in converter code emitting the records —
instead of copying whatever `nealseed.json` happens to contain. nealseed
itself is NOT modified (its scheme records simply stop being the
source; if the loader must still tolerate their presence, ignore-don't-
copy). Keep pks/names stable with what downstream passes expect
(`scheme_by_name`, `scheme_fields_by_pk`, task money-block stamping) —
read those consumers first; the invariant is that regenerated
converted.json is byte-equivalent for scheme-dependent output unless a
scheme genuinely changed. Include one flat_fee scheme in the internal
table (exercises the new algorithm end-to-end in converted data — a
"Delivery" ServiceItem with an amount config is optional but cheap if
the converter already emits service items; check).
- [ ] TDD: invariant test (schemes in output come from the internal
  table; count/names pinned) RED against current copy-from-nealseed
  behavior → implement → GREEN. Run `tests.test_neals_builders` (all)
  + the fixture suite (`tests.test_neals_fixture`) against a
  regenerated converted.json.
- [ ] Commit.

### Task 5: e2e — flat-fee catalog journey

**Files:**
- Create: `e2e/specs/estimating-structure/flat-fee.spec.js`
  (conventions from `mint-and-release.spec.js`: API-built fixtures,
  personas, test.step, scoped selectors, twice-green before commit)

- [ ] One journey: create a "Flat fee" scheme via UI (Settings → rate
  schemes surface — find where RateSchemeManager mounts; assert rate
  input absent/locked); create ServiceItem "Delivery" with Amount $50
  (assert no 'modifier' text on the form); estimate: Add line → search
  picks Delivery, line lands qty 1 × $50; accept via API → crystallized
  task's rate is 50 (assert via API); the checklist never asked about
  the catalog line.
- [ ] Green twice; commit.

### Task 6: docs + verification gate

**Files:**
- Modify: `docs/designs/estimates-and-prices.md` (RateScheme section:
  the fourth algorithm, scheme-owned config interpretation, the $0
  manual-stamp edge), `docs/designs/architecture-and-conventions.md`
  (if it catalogs scheme algorithms), `docs/designs/data-constraints.md`
  (flat_fee validation rules), `docs/plans/2026-08-09-rm-review-checklist.md`
  (click-through: flat-fee scheme creation, amount on service item,
  pick-to-line, no modifier wording), `docs/designs/LATER.md` (flat-fee
  entry: repeatable-fee half now SHIPPED; discoverability half stays),
  `docs/plans/2026-08-16-flat-fee-schemes.md` (status → implemented).
- [ ] Docs, then gates IN ORDER, one at a time: full Vitest; full
  Django FRESH DB (no --keepdb), summary-line judged; e2e
  `specs/estimating-structure/` + the estimate-surface regression
  specs. Record verbatim summary lines.
- [ ] Commit.

## Self-review notes (applied)

- Encapsulation enforced structurally: Tasks 1-2 put every branch
  inside RateScheme; the constraint block tells reviewers to fail any
  diff to Task.effective_rate/copy_active_modifiers/
  validate_active_modifiers/gates/bundle math.
- Spec coverage: algorithm constant→1; item-side amounts + no-mixing
  validation→1-2; stamp-into-rate→1-2; UI (scheme manager, Amount
  field, picker price, no 'modifier' wording)→3; converter companion→4;
  $0 manual edge pinned→1; docs+LATER flip→6.
- Type consistency: `FLAT_FEE`/'flat_fee', `resolve_stamp`,
  `validate_item_config`, `display_rate` used consistently throughout.
- Deliberately absent: percent mixing (rejected), hand-line changes,
  migrating RM's interim Setup-fee scheme (RM regenerates dev data),
  WorkTemplate material associations (untouched by this feature).
