# Phase 2 — Estimating starts on the Plan (reuse the create-worksheet flow)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the **Plan** (EstWorksheet) the entry point for estimating a job, by
**reusing the existing create-worksheet flow** — minimal changes. Today the job's
"Create Estimate" button makes a *bare* Estimate that bypasses the Plan; the
`/jobs/{id}/create-worksheet` page already creates a worksheet (blank or from a
WorkTemplate — that template option **is** Express). Phase 2: rename the job's CTA
to **"Start Estimate"** and point it at that create flow (shown when the job has no
Plan yet), and make worksheet creation **idempotent** so a job never ends up with
two Plans. The template/Express flow is **left untouched** (the user will rework it
later). The "Open Estimate" state (when a Plan already exists) is **deferred** to
the later plan-view/pillar work — for now an existing Plan is reached via the job's
existing worksheets section.

**Architecture:** One small backend change (worksheet create becomes get-or-create,
one Plan per job; a template only scaffolds a freshly-created Plan) + one frontend
change (swap the job's "Create Estimate" button for "Start Estimate" that routes to
the existing create-worksheet page). The Estimate (Client View) is still produced
later by the existing wizard (`open-estimate` / `send-all-atoms`) on projection —
unchanged. We do **not** remove the direct line-authoring path, do **not** touch
the template/Express flow, and do **not** start the vocabulary/pillar rollout
(all later phases).

**Tech Stack:** Django + DRF (`apps/estimates/services.py`, `apps/api/worksheets/`),
Svelte 5 runes SPA, Vitest, Django `TestCase`.

## Global Constraints

- **No model changes → no migrations.** Service + frontend only.
- **Never write the dev database.** Backend tests on the test DB only:
  `python manage.py test <module> --keepdb` (one process; never parallel agents). No
  `migrate`/`loaddata`/`shell` writes, no dev server. Frontend: `cd frontend && npm
  run test:run` (never watch mode).
- **One Plan per job.** Worksheet creation must be idempotent — never produce a
  second worksheet for a job that already has one; if old data has several, operate
  on the latest (`est_worksheet_id` desc, matching `JobDetail.currentWorksheet`).
- **Reuse, don't rebuild, and minimize churn.** Do not add a parallel endpoint or a
  duplicate template picker. **Do not modify the template/Express flow** in
  `CreateWorksheetPage` (it's being reworked later) beyond what reuse requires —
  i.e. don't relabel or restructure it.
- **Svelte 5 runes**; match sibling conventions; reuse JobDetail's existing
  navigation helper; `api.js` lists are `resp.results || resp`.
- **Do NOT remove** the direct-estimate backend path or the second authoring
  surface (later phase). **Do NOT** add the "Open Estimate" state or the
  Plan/Client-View vocabulary/pillar rollout (later phase).

## Reference: what exists today (read before starting)

- `apps/estimates/services.py` `WorksheetService.create_worksheet(job_pk, **kwargs)`
  (~L805): `EstWorksheet(job=job)` + save — **creates a new worksheet every call**.
- `apps/api/worksheets/views.py` `perform_create` (~L70):
  `ws = create_worksheet(job_pk)`; if `template` in payload,
  `template.generate_tasks_for_worksheet(ws)` +
  `template.generate_materials_for_worksheet(ws, task_pairing=…)`.
- `frontend/src/routes/jobs/CreateWorksheetPage.svelte` (route
  `/jobs/{id}/create-worksheet`): optional WorkTemplate `<select>` (Express), POSTs
  `{job, template?}` to `/api/est-worksheets/`, navigates to `/worksheets/{id}`.
  **Leave this file alone.**
- `frontend/src/components/jobs/JobDetail.svelte`: `currentWorksheet` (~L233,
  latest); `currentEstimate` (~L52); `canCreateEstimate` (~L317,
  `job.status in ['draft','submitted'] && !currentEstimate`); `createEstimate()`
  (~L323, `POST /api/estimates/` then navigates to the estimate). This button +
  gate + handler are what Task 2 changes.
- Tests: `tests/test_api_worksheets.py`, `tests/test_estworksheet.py`,
  `frontend/tests/components/...` (JobDetail).

---

## Task 1: Make worksheet creation idempotent (one Plan per job)

So reusing the create flow as "the Plan" can't silently make a second worksheet
(double-submit, direct nav, races).

**Files:**
- Modify: `apps/estimates/services.py` (add `get_or_create_worksheet`)
- Modify: `apps/api/worksheets/views.py` (`perform_create` uses it; template only
  scaffolds a freshly-created Plan)
- Test: `tests/test_api_worksheets.py`

**Interfaces:**
- Produces: `WorksheetService.get_or_create_worksheet(job_pk, **kwargs) -> (EstWorksheet, created: bool)`
  — returns the job's latest worksheet (created=False) or a new one (created=True).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_worksheets.py
def test_get_or_create_worksheet_idempotent(self):
    ws1, c1 = WorksheetService.get_or_create_worksheet(self.job.pk)
    ws2, c2 = WorksheetService.get_or_create_worksheet(self.job.pk)
    self.assertTrue(c1); self.assertFalse(c2)
    self.assertEqual(ws1.pk, ws2.pk)
    self.assertEqual(EstWorksheet.objects.filter(job=self.job).count(), 1)

def test_post_worksheet_twice_does_not_duplicate(self):
    self.client.post('/api/est-worksheets/', {'job': self.job.pk}, format='json')
    self.client.post('/api/est-worksheets/', {'job': self.job.pk}, format='json')
    self.assertEqual(EstWorksheet.objects.filter(job=self.job).count(), 1)

def test_post_with_template_on_existing_plan_does_not_re_scaffold(self):
    self.client.post('/api/est-worksheets/', {'job': self.job.pk}, format='json')
    before = PlanTask.objects.filter(est_worksheet__job=self.job).count()
    self.client.post('/api/est-worksheets/',
                     {'job': self.job.pk, 'template': self.work_template.pk}, format='json')
    after = PlanTask.objects.filter(est_worksheet__job=self.job).count()
    self.assertEqual(before, after)  # existing Plan returned, template ignored
```

- [ ] **Step 2: Run, confirm fail** — `python manage.py test tests.test_api_worksheets --keepdb`

- [ ] **Step 3: Implement** — add `get_or_create_worksheet` (latest-or-create,
  returning `(ws, created)`); change `perform_create` to use it and only run the
  template scaffold when `created` is True:

```python
# perform_create
ws, created = WorksheetService.get_or_create_worksheet(job_pk)
template = data.pop('template', None)
if created and template:
    task_pairing = template.generate_tasks_for_worksheet(ws)
    template.generate_materials_for_worksheet(ws, task_pairing=task_pairing)
serializer.instance = ws
```

- [ ] **Step 4: Run + reconcile** — `python manage.py test tests.test_api_worksheets --keepdb`.
  Update any existing test that assumed each POST makes a *new* worksheet (that is
  the behavior we're deliberately changing). Don't weaken unrelated assertions.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py apps/api/worksheets/views.py tests/test_api_worksheets.py
git commit -m "feat(plan): worksheet creation is idempotent (one Plan per job)"
```

---

## Task 2: Job CTA becomes "Start Estimate" → the create-worksheet flow

Swap the job's bare-estimate button for one that starts the Plan, reusing the
existing create flow. Shown when the job has no Plan yet.

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte`
- Test: `frontend/tests/components/jobs/JobDetail.test.js` (create if absent)

**Interfaces:** reuses `currentWorksheet` (already derived), the existing
`/jobs/{id}/create-worksheet` route, and JobDetail's navigation helper.

- [ ] **Step 1: Write the failing test** — render JobDetail for a startable job
  (status in draft/submitted) **with no worksheet**: assert a **"Start Estimate"**
  button is present and navigates to `#/jobs/{job_id}/create-worksheet`. Assert the
  old "Create Estimate" label is gone and that no `POST /api/estimates/` is fired by
  this button. (When `currentWorksheet` exists, the button is not shown — the Plan
  is reached via the existing worksheets section; "Open Estimate" is a later phase.)
  Model on the existing JobDetail test setup/mocks.

- [ ] **Step 2: Run, confirm fail** — `cd frontend && npm run test:run -- tests/components/jobs/JobDetail.test.js`

- [ ] **Step 3: Implement** — relabel the button **"Start Estimate"**; change its
  visibility gate from `… && !currentEstimate` to `… && !currentWorksheet` (show it
  when the job is startable and has no Plan yet); change its handler from
  `POST /api/estimates/` to navigate to `/jobs/${job.job_id}/create-worksheet`
  (drop the bare-estimate call from this entry — the backend path stays, just not
  wired here). Leave the worksheets section and everything else untouched.

- [ ] **Step 4: Run the file + full suite** — `cd frontend && npm run test:run`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte frontend/tests/components/jobs/JobDetail.test.js
git commit -m "feat(plan): job 'Start Estimate' opens the create-worksheet flow (the Plan)"
```

---

## Done-when

- A startable job with no Plan shows a **"Start Estimate"** button that goes to the
  existing create-worksheet flow (blank or template = Express) and lands on the Plan
  (the Phase-1 build view). The bare-estimate button is gone from this entry.
- Worksheet creation is **idempotent** — a job never gets a second Plan; a template
  only scaffolds a freshly-created Plan.
- The template/Express flow (`CreateWorksheetPage`) is **unchanged**.
- The Estimate (Client View) is still produced by the existing wizard on
  projection — unchanged. The direct line-authoring path still exists (not removed).
- `tests/test_api_worksheets` + full `npm run test:run` green. No migrations.

## Out of scope (later phases — design draft §14 + user's stated reworks)

- The **template/Express rework** (the user is redoing it) — touch it as little as
  possible here; no relabeling/restructuring `CreateWorksheetPage`.
- The **"Open Estimate"** state when a Plan already exists (deferred to the
  plan-view/pillar work) — for now an existing Plan is reached via the job's
  worksheets section.
- Removing the direct-estimate path / second authoring surface + Phase B carry-over.
- The Plan / Client View vocabulary rollout, the Estimate-pillar toggle, the
  combined Tasks & Materials pillar; line-item slimming, invoice parity, seed/doc.
- An estimate-creation backstop (Plan-first flow makes it unnecessary now).
- Applying a template onto an *existing* Plan (idempotent create ignores the
  template when a Plan exists — see Decision 3).

## Decisions (confirmed with the user)

1. **Reuse `CreateWorksheetPage` + reroute, no new endpoint** — the only backend
   change is making the existing create idempotent.
2. **Button copy: "Start Estimate"** (shown when no Plan). The **"Open Estimate"**
   state (Plan exists) is **deferred** to the later plan-view/pillar phase; for now
   the existing worksheets section is the way into an existing Plan.
3. **Idempotent create ignores a template when a Plan already exists** (no
   re-scaffold over existing work).
4. **Leave the template/Express flow alone** — the user will rework it later, so
   make as few changes as feasible there (no relabel, no restructure). A temporary
   copy mismatch (button says "Start Estimate", the create page still says
   "Worksheet") is accepted and resolved in that later rework.
