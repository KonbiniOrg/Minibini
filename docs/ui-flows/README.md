# UI flows

From-the-user's-perspective walkthroughs of how each feature behaves in the SPA.

**Two audiences, one document:**
- **Manual / user testing** — a checklist you can run top-to-bottom in the browser
  without missing edge cases or permission variations.
- **The automated UI test platform** (planned) — each `[ ]` step is written to map
  to a single assertion, so these docs seed test cases rather than being rewritten.

These describe **built behavior**, like `docs/designs/` — keep them current when
the UI changes. They differ from `docs/designs/` (which explains *how/why the
system works*, for developers) by being *scripts a user or test runner follows*.
They are not disposable like `docs/plans/`.

## One file per feature flow

- `Expenses.md`, `Invoicing.md`, … — title-case feature name. Start a new file
  when a flow is substantial enough to test on its own; cross-link rather than
  duplicate where flows meet (e.g. Expenses §7 references the invoice wizard).

## House shape

Keep every doc in the same structure so the test platform can parse them
predictably:

1. **`# <Feature> — UI flow`** + a one-paragraph **Purpose**.
2. **Personas** — the user variants whose behavior differs (by permission atom,
   ownership, etc.). Most flows need at least a low-privilege and a high-privilege
   persona.
3. **Dev notes** (optional) — environment caveats that look like bugs but aren't
   (e.g. "company expenses need QBO connected").
4. **Numbered flow sections** — each a short scenario, its steps as GFM task-list
   checkboxes:
   - `- [ ] **Label:** action → expected result.`
   - One observable assertion per box. Name the route (`#/jobs/{id}/tasklist`) and
     the button/field text so a step is reproducible by a person *or* a script.
   - Call out *guards* (things that should be blocked) as their own boxes —
     they're the most-missed and the highest-value to automate.
5. **Coverage matrix** — a table of the orthogonal dimensions (attachment,
   payment, persona, permission, state-guards, …) × the cases to hit, so gaps are
   visible at a glance.

## Writing the steps

- **Observable, not internal.** Assert what the user sees ("Spent rises by the
  amount", "the field is disabled"), not service internals.
- **Reproducible.** Include the entry point and the control's visible label.
- **Permission-explicit.** When a step depends on a persona, say which.
- **Honest expectations.** If a step's result looks surprising but is correct,
  say so — and tell the tester to report deviations as likely bugs.

See `Expenses.md` as the reference implementation of this shape.
