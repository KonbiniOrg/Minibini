"""
Management command to validate loaded data against business constraints.

Checks constraints that are enforced in save()/clean() methods but bypassed
by fixture loading (loaddata). Reports all issues found without modifying data.

Usage:
    python manage.py validate_data
    python manage.py validate_data --fix  # Auto-fix where safe to do so

Check summary
=============

Per-model field checks:
  Contact          E  email required
                   E  at least one phone number required
  Business         E  default_contact required
                   E  default_contact must belong to this business
                   W  empty reference code
  Job              E  valid status value
                   W  approved+ : missing start_date
                   W  draft/submitted/rejected: stray start_date
                   W  completed/cancelled/rejected: missing completed_date
                   W  non-terminal: stray completed_date
  RateScheme       E  valid algorithm value
                   E  missing accounting_category
                   E  negative rate only allowed for percentage algorithm
                   E  elapsed_time scheme must be pinned to the hour unit
  Estimate         E  valid status value
                   E  max one accepted estimate per job
                   E  max one draft estimate per job
                   E  draft: must not have sent_date or closed_date
                   W  open: missing sent_date
                   W  accepted/rejected/superseded/expired: missing closed_date
  Task             E  must belong to a Job
                   E  valid status value
                   E  valid qty_source value
                   E  negative rate
                   E  active_modifiers must be a list of {key, percent} dicts
  Material         E  must have description or inventory_item
                   E  negative quantity
                   W  has PLI but empty description (--fix: auto-fill)
  LineItems        E  cannot have both task and inventory_item (mutual exclusivity)
  (all 4 types)    W  negative price
  EstimateLI       E  hand line (no atom source, not adjustment) missing accounting_category
  ChangeOrderLI    E  bare ADD line (no descriptor/atom source) missing accounting_category
  InvoiceLI        E  non-draft/non-dead invoice's line missing accounting_category
                      (Task accounting_category is nullable and NOT checked —
                      Phase 3: a task may stay uncategorized until invoicing)
  PurchaseOrder    E  valid status value
                   E  contact must have a business
                   W  non-draft: missing issued_date
                   W  received_in_full: missing received_date
                   W  cancelled: missing cancel_date
                   E  contact must have a business
                   E  cannot link to draft PO
                   E  non-draft must have at least one line item
  Invoice          E  valid status value
  Deliverable      E  must belong to a Job; qty_ordered must be positive
                   W  missing units
  Shipment         E  valid status value
                   E  picked_up missing picked_up_date / prepared has one
                   W  job has no accepted estimate
  ShipmentItem     E  qty must be positive
                   E  shipped qty per deliverable exceeds qty_ordered
  InventoryItem    E  missing accounting_category (causes silent tax-exemption)
                   E  negative purchase_price, selling_price, qty_on_hand, qty_sold, qty_wasted
                   E  duplicate code
                   W  not inventoried but has non-zero quantity values
  Earmark          E  non-positive quantity
                   E  PLI must be inventoried
                   W  quantity exceeds QOH
  InvAdjustment    W  PLI not inventoried

Cross-model relationship checks:
  Est versioning   E  lower-version estimate with same number must be 'superseded'
                   W  parent chain should link sequential versions
  Job/Est status   E  approved job must have exactly one accepted estimate
                   W  completed job: missing accepted estimate (may predate estimate workflow)
                   E  draft/submitted job must not have accepted estimate
                   E  accepted estimate's job must not be draft/submitted/rejected
                   E  open estimate's job must not be draft/rejected (signal should
                      have moved job to submitted+)
                   E  completed/cancelled job must not have draft/open estimates
  PO contact/biz   E  contact's business must match PO's business
  Earmark/Job      W  earmark on completed/cancelled/rejected job
  Invoice/Job      W  invoice on draft/submitted/rejected job
                   E  cancelled job's invoices must also be cancelled
"""
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.db.models import Sum, Count

from apps.core.units import HOUR_UNIT

from apps.jobs.models import Job
from apps.estimates.models import Estimate
from apps.purchasing.models import PurchaseOrder
from apps.invoicing.models import Invoice


class Command(BaseCommand):
    help = 'Validate loaded data against business logic constraints'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Auto-fix issues where safe to do so (e.g., missing descriptions on materials)',
        )

    def handle(self, *args, **options):
        self.fix = options['fix']
        self.errors = []
        self.warnings = []
        self.fixes = []

        # Per-model field-level checks
        self.check_contacts()
        self.check_businesses()
        self.check_jobs()
        self.check_rate_schemes()
        self.check_estimates()
        self.check_tasks()
        self.check_bleps_and_shifts()
        self.check_materials()
        self.check_line_items()
        self.check_estimate_line_categories()
        self.check_change_order_line_categories()
        self.check_invoice_line_categories()
        self.check_purchase_orders()
        self.check_invoices()
        self.check_deliverables()
        self.check_shipments()
        self.check_shipment_items()
        self.check_inventory_items()
        self.check_earmarks()

        # Cross-model relationship invariants
        self.check_estimate_versioning()
        self.check_job_estimate_status_alignment()
        self.check_po_contact_business_match()
        self.check_earmark_job_status()
        self.check_invoice_job_status()
        self.check_job_work_complete_gate()
        self.check_estimate_source_job_consistency()
        self.check_invoice_source_job_consistency()
        self.check_agreement_line_invoice_exclusivity()

        # Report
        self.stdout.write('')
        if self.fixes:
            self.stdout.write(self.style.SUCCESS(f'Fixed {len(self.fixes)} issue(s):'))
            for fix in self.fixes:
                self.stdout.write(f'  [FIXED] {fix}')

        if self.warnings:
            self.stdout.write(self.style.WARNING(f'\n{len(self.warnings)} warning(s):'))
            for warning in self.warnings:
                self.stdout.write(f'  [WARN] {warning}')

        if self.errors:
            self.stdout.write(self.style.ERROR(f'\n{len(self.errors)} error(s):'))
            for error in self.errors:
                self.stdout.write(f'  [ERROR] {error}')
        else:
            self.stdout.write(self.style.SUCCESS('\nNo errors found.'))

    # ── Contacts ──────────────────────────────────────────────

    def check_contacts(self):
        from apps.contacts.models import Contact
        for c in Contact.objects.all():
            if not c.email or not c.email.strip():
                self.errors.append(f'Contact {c.pk} ({c.name}): missing email')
            if not any([c.work_number, c.mobile_number, c.home_number]):
                self.errors.append(f'Contact {c.pk} ({c.name}): no phone number (need at least one)')

    # ── Businesses ────────────────────────────────────────────

    def check_businesses(self):
        from apps.contacts.models import Business
        for b in Business.objects.select_related('default_contact').all():
            if not b.default_contact_id:
                self.errors.append(f'Business {b.pk} ({b.business_name}): no default_contact')
            elif b.default_contact.business_id != b.pk:
                self.errors.append(
                    f'Business {b.pk} ({b.business_name}): default_contact {b.default_contact.pk} '
                    f'belongs to business {b.default_contact.business_id}, not this one'
                )
            if not b.our_reference_code:
                self.warnings.append(f'Business {b.pk} ({b.business_name}): empty reference code')

    # ── Jobs ──────────────────────────────────────────────────

    def check_jobs(self):
        from apps.jobs.models import Job
        valid_statuses = {s[0] for s in Job.JOB_STATUS_CHOICES}
        for j in Job.objects.all():
            if j.status not in valid_statuses:
                self.errors.append(f'Job {j.job_number}: invalid status "{j.status}"')
            # Approved and beyond should have start_date (set on approval)
            if j.status in (Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
                            Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED,
                            Job.STATUS_CANCELLED) and not j.start_date:
                self.warnings.append(f'Job {j.job_number}: status is {j.status} but no start_date')
            # Pre-approval states should not carry a start_date
            if j.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED,
                            Job.STATUS_REJECTED) and j.start_date:
                self.warnings.append(f'Job {j.job_number}: status is {j.status} but start_date is set')
            # Terminal states should have completed_date
            if j.status in (Job.STATUS_COMPLETED, Job.STATUS_CANCELLED,
                            Job.STATUS_REJECTED) and not j.completed_date:
                self.warnings.append(f'Job {j.job_number}: status is {j.status} but no completed_date')
            # Non-terminal states should not carry a completed_date
            if j.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED,
                            Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
                            Job.STATUS_WORK_COMPLETE) and j.completed_date:
                self.warnings.append(f'Job {j.job_number}: status is {j.status} but completed_date is set')

    # ── Bleps & Shifts ────────────────────────────────────────

    def check_bleps_and_shifts(self):
        """Enforce the time-tracking invariants (data-constraints §1.2a/§1.11/§1.12):
        a Blep's task is never pending; every closed Blep is enclosed by a Shift
        of the same user; no two of a user's Bleps overlap.
        """
        from collections import defaultdict
        from apps.jobs.models import Blep, Task
        from apps.core.models import Shift

        bleps = list(Blep.objects.select_related('task', 'user').all())

        # A Task with any Blep must not be pending.
        for b in bleps:
            if b.task.status == Task.STATUS_PENDING:
                self.errors.append(
                    f'Blep {b.pk}: task {b.task.pk} is pending but has a blep')

        shifts_by_user = defaultdict(list)
        for s in Shift.objects.all():
            shifts_by_user[s.user_id].append(s)
        bleps_by_user = defaultdict(list)
        for b in bleps:
            bleps_by_user[b.user_id].append(b)

        for user_id, ubleps in bleps_by_user.items():
            ushifts = shifts_by_user.get(user_id, [])
            # Enclosure: each closed blep fully inside some shift of the same user.
            for b in ubleps:
                if b.start_time is None or b.end_time is None:
                    continue
                # An ongoing shift (end_time is None) is still running, so it
                # encloses any blep starting at/after its start — matching
                # enclosing_shift_for_blep / unenclosed_bleps_for_shift.
                enclosed = any(
                    s.start_time is not None
                    and s.start_time <= b.start_time
                    and (s.end_time is None or b.end_time <= s.end_time)
                    for s in ushifts
                )
                if not enclosed:
                    self.errors.append(
                        f'Blep {b.pk}: not enclosed by any shift of user {user_id}')
            # No overlapping bleps for one user.
            closed = sorted(
                (b for b in ubleps if b.start_time and b.end_time),
                key=lambda b: b.start_time)
            for prev, cur in zip(closed, closed[1:]):
                if cur.start_time < prev.end_time:
                    self.errors.append(
                        f'Blep {cur.pk}: overlaps blep {prev.pk} for user {user_id}')

    # ── Estimates ─────────────────────────────────────────────

    def check_estimates(self):
        from apps.estimates.models import Estimate
        from apps.jobs.models import Job
        valid_statuses = {s[0] for s in Estimate.ESTIMATE_STATUS_CHOICES}

        for e in Estimate.objects.select_related('job').all():
            if e.status not in valid_statuses:
                self.errors.append(f'Estimate {e.estimate_number}: invalid status "{e.status}"')

            # Open estimates should have sent_date
            if e.status == Estimate.STATUS_OPEN and not e.sent_date:
                self.warnings.append(f'Estimate {e.estimate_number}: status is open but no sent_date')

            # Terminal states should have closed_date
            if e.status in (Estimate.STATUS_ACCEPTED, Estimate.STATUS_REJECTED, Estimate.STATUS_SUPERSEDED, Estimate.STATUS_EXPIRED) and not e.closed_date:
                self.warnings.append(f'Estimate {e.estimate_number}: status is {e.status} but no closed_date')

            # Draft estimates must not have sent_date or closed_date — the model's
            # save() only populates these on transitions out of draft, so if they're
            # set, the data was hand-built bypassing the model.
            if e.status == Estimate.STATUS_DRAFT:
                if e.sent_date:
                    self.errors.append(
                        f'Estimate {e.estimate_number} v{e.version}: status is draft but sent_date is set'
                    )
                if e.closed_date:
                    self.errors.append(
                        f'Estimate {e.estimate_number} v{e.version}: status is draft but closed_date is set'
                    )

        # Only one accepted estimate per job
        # Only one draft estimate per job (older drafts should be superseded
        # before a new revision is opened)
        for job in Job.objects.all():
            accepted_count = Estimate.objects.filter(job=job, status=Estimate.STATUS_ACCEPTED).count()
            if accepted_count > 1:
                self.errors.append(
                    f'Job {job.job_number}: has {accepted_count} accepted estimates (max 1)'
                )
            draft_count = Estimate.objects.filter(job=job, status=Estimate.STATUS_DRAFT).count()
            if draft_count > 1:
                self.errors.append(
                    f'Job {job.job_number}: has {draft_count} draft estimates (max 1)'
                )

    # ── Tasks ─────────────────────────────────────────────────

    def check_tasks(self):
        from apps.jobs.models import Task
        from apps.estimates.models import ServiceItem
        valid_task_statuses = {s[0] for s in Task.TASK_STATUS_CHOICES}
        valid_qty_sources = {s[0] for s in Task.QTY_SOURCE_CHOICES}
        # Tasks now belong directly to a Job (post-WorkOrder-removal) and own
        # their money block (task-owned-money Phase 1): qty_source, rate,
        # unit_label, accounting_category, active_modifiers are the task's
        # own fields, not read through source_scheme (provenance only — a
        # null source_scheme from SET_NULL preset deletion is legal, no
        # check needed). A null accounting_category is ALSO legal (Phase 3):
        # a task may go uncategorized until invoicing, where the configured
        # fallback AC stamps the invoice line — no check needed here either.
        for t in Task.objects.select_related('job').all():
            if not t.job_id:
                self.errors.append(f'Task {t.pk} ({t.name}): not attached to a Job')
            if t.status not in valid_task_statuses:
                self.errors.append(f'Task {t.pk} ({t.name}): invalid status "{t.status}"')
            if t.qty_source not in valid_qty_sources:
                self.errors.append(f'Task {t.pk} ({t.name}): invalid qty_source "{t.qty_source}"')
            if t.rate is not None and t.rate < 0:
                self.errors.append(f'Task {t.pk} ({t.name}): negative rate {t.rate}')
            self._check_task_active_modifiers_shape(t)
        # parent_task is DORMANT (better-fees spec §3; flattened by
        # jobs/0061): the field survives in the schema but no code may
        # write it — a non-NULL value means some path still does, and its
        # on_delete=CASCADE makes stale pointers actively dangerous.
        for t in Task.objects.filter(parent_task__isnull=False):
            self.errors.append(
                f'Task {t.pk} ({t.name}): parent_task={t.parent_task_id} is '
                f'set — the field is dormant (subtasks removed, better-fees '
                f'spec §3); some code path is still writing it'
            )
        # ServiceItems stamp Tasks at generate-time and still store plain
        # modifier-key lists (not the {key, percent} snapshot shape Tasks
        # use) — default_active_modifiers just needs to be a list.
        for tt in ServiceItem.objects.all():
            if isinstance(tt.default_active_modifiers, dict):
                self.errors.append(
                    f'ServiceItem {tt.pk} ({tt.template_name}): '
                    f'default_active_modifiers is a dict; must be a list of keys'
                )

    def _check_task_active_modifiers_shape(self, t):
        """A Task's active_modifiers is a snapshot list of {key, label,
        percent} dicts (label optional) stamped at creation time — never a
        dict, never bare/malformed entries."""
        modifiers = t.active_modifiers
        if not isinstance(modifiers, list):
            self.errors.append(
                f'Task {t.pk} ({t.name}): active_modifiers is a '
                f'{type(modifiers).__name__}; must be a list of {{key, percent}} dicts'
            )
            return
        for m in modifiers:
            if not isinstance(m, dict):
                self.errors.append(
                    f'Task {t.pk} ({t.name}): active_modifiers entry {m!r} is not '
                    f'a dict (expected {{key, percent}})'
                )
                continue
            if not m.get('key'):
                self.errors.append(
                    f'Task {t.pk} ({t.name}): active_modifiers entry {m!r} missing key'
                )
            try:
                Decimal(str(m.get('percent')))
            except (InvalidOperation, TypeError, ValueError):
                self.errors.append(
                    f'Task {t.pk} ({t.name}): active_modifiers entry {m!r} '
                    f'percent must be numeric'
                )

    # ── Materials ─────────────────────────────────────────────

    def check_materials(self):
        from apps.inventory.models import Material
        # Check Materials (work-order side)
        for m in Material.objects.select_related('inventory_item', 'task').all():
            if not m.description and not m.inventory_item:
                self.errors.append(
                    f'Material {m.pk}: no description and no inventory_item (nothing to derive from)'
                )
            # Auto-fill check: if PLI linked, description should match or be explicitly set
            if m.inventory_item and not m.description:
                if self.fix:
                    m.description = m.inventory_item.description[:255]
                    m.save()
                    self.fixes.append(f'Material {m.pk}: set description from PLI')
                else:
                    self.warnings.append(f'Material {m.pk}: has PLI but empty description')
            # Negative quantities
            if m.quantity < 0:
                self.errors.append(f'Material {m.pk} ({m.description}): negative quantity {m.quantity}')

    # ── Line Items (all types) ────────────────────────────────

    def check_line_items(self):
        from apps.estimates.models import EstimateLineItem
        from apps.invoicing.models import InvoiceLineItem
        from apps.purchasing.models import PurchaseOrderLineItem

        # (name, model, has_task_fk) — EstimateLineItem.task FK was dropped in
        # favour of EstimateLineItemSource; InvoiceLineItem.task was dropped for
        # InvoiceLineItemSource. Neither can use select_related('task').
        line_item_models = [
            ('EstimateLineItem', EstimateLineItem, False),
            ('InvoiceLineItem', InvoiceLineItem, False),
            ('PurchaseOrderLineItem', PurchaseOrderLineItem, True),
        ]

        for name, model, has_task_fk in line_item_models:
            if has_task_fk:
                qs = model.objects.select_related('task', 'inventory_item').all()
            else:
                qs = model.objects.select_related('inventory_item').all()
            for li in qs:
                # Mutual exclusivity: cannot have both task and inventory_item
                # (only applicable to models that still have a task FK)
                if has_task_fk and li.task and li.inventory_item:
                    self.errors.append(
                        f'{name} {li.pk}: has both task and inventory_item (mutually exclusive)'
                    )
                # Negative price
                if li.price < 0:
                    self.warnings.append(f'{name} {li.pk}: negative price {li.price}')

    # ── Line item accounting_category nullability (Phase 3) ────

    def check_estimate_line_categories(self):
        """A hand-authored estimate line (no atom source, not a percentage
        adjustment) must carry an accounting_category —
        EstimateService.add_line_item / update_line_item /
        assert_all_hand_lines_have_ac (apps/estimates/services.py) all
        enforce this at every mutation + at send-time (Decision 1). A
        survivor with none is a save()/full_clean() bypass (fixture
        loading, direct ORM create), not a legal state — ERROR.

        Atom-backed lines (an EstimateLineItemSource exists) are exempt:
        a null-AC Task atom legitimately collapses the line's category to
        None (Phase 3 Task 4). Adjustment lines (`adjustment_service_id`
        set) are exempt too: a percentage adjustment targets other lines'
        categories, it never carries one of its own. Same predicate as
        assert_all_hand_lines_have_ac."""
        from apps.estimates.models import EstimateLineItem
        for li in EstimateLineItem.objects.select_related('estimate').filter(
            accounting_category_id__isnull=True,
            adjustment_service_id__isnull=True,
        ):
            if li.sources.exists():
                continue
            self.errors.append(
                f'EstimateLineItem {li.pk} (estimate {li.estimate.estimate_number}): '
                f'hand line (no atom source, not an adjustment) has no accounting_category'
            )

    def check_change_order_line_categories(self):
        """A bare ADD line on a change order (no service_item/inventory_item
        descriptor, no atom source) must carry an accounting_category —
        ChangeOrderService.assert_all_bare_add_lines_have_ac enforces this
        at send-time. A survivor with none is a bypass, not a legal state
        — ERROR. Remove/replace lines are out of scope (mirrors the real
        gate: assert_all_bare_add_lines_have_ac only ever inspects
        action=ADD lines — a non-adjustment REPLACE line's category is a
        separate, pre-existing gap, not something Phase 3 introduced or
        this check should invent). Descriptor-backed (service_item/
        inventory_item) and atom-backed (sources exist) ADD lines are
        exempt, same predicate as the real gate."""
        from apps.estimates.models import ChangeOrderLineItem
        for li in ChangeOrderLineItem.objects.select_related('change_order').filter(
            action=ChangeOrderLineItem.ACTION_ADD,
            service_item_id__isnull=True,
            inventory_item_id__isnull=True,
            accounting_category_id__isnull=True,
        ):
            if li.sources.exists():
                continue
            self.errors.append(
                f'ChangeOrderLineItem {li.pk} '
                f'(CO {li.change_order.change_order_number}): bare ADD line '
                f'(no descriptor, no atom source) has no accounting_category'
            )

    def check_invoice_line_categories(self):
        """An invoice line's accounting_category may be null only while its
        invoice hasn't (yet, or ever) passed
        InvoiceEmailService._assert_all_lines_categorized — the send-time
        gate in apps/invoicing/services.py that requires EVERY line
        (including adjustment lines; the gate applies no adjustment
        exemption) to carry a category before send_invoice flips status
        off draft.

        So null is legal on:
          - draft invoices (pre-send: a manual hand line from
            InvoiceService.add_line_item is never required to carry an AC
            at add-time — deferred to the send gate by design, see the
            Phase 3 Task 5 report's "estimate/invoice hand-line
            AC-requirement discrepancy" note. An agreement-seeded
            adjustment line is NOT normally null: in production it always
            carries the source estimate/CO adjustment's own real AC —
            EstimateService.add_adjustment_line / the CO equivalent both
            stamp `svc.accounting_category` off the (required,
            non-nullable) PERCENTAGE RateScheme field, and
            InvoiceService._agreement_category_id passes that value
            through unmodified (never fallback-stamped, since an
            adjustment targets *other* lines' categories, but never
            stripped to null either — a final-review fix corrected an
            earlier bug where the adjustment exemption discarded the real
            AC). A null adjustment-line AC can therefore only arise from
            legacy/hand-built data — e.g. a raw-ORM-created
            EstimateLineItem/ChangeOrderLineItem adjustment row that
            bypassed the real creation service — and, once seeded onto a
            draft invoice, still blocks send exactly like any other
            uncategorized line);
          - cancelled/superseded invoices (InvoiceService.cancel routes a
            draft invoice straight to cancelled via Invoice.save(), never
            through the send gate — DEAD_INVOICE_STATUSES,
            apps/invoicing/claims.py).

        Every other status (open/partly-paid/paid/defaulted) is only
        reachable by having passed the gate (send_invoice is the sole
        draft-exit path; QBO polling only ever moves an already-open
        invoice to partly-paid/paid), so a null AC surviving there is a
        genuine gate-bypass / data corruption — ERROR. Deliberately NOT
        scoped by adjustment vs. non-adjustment: post-gate, the gate
        itself makes no such distinction, so neither does this check.

        Task.accounting_category is separately nullable and NOT checked
        here or anywhere in validate_data (Phase 3 Task 4) — a task may
        stay uncategorized until invoicing, where the wizard stamps the
        configured fallback."""
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.claims import DEAD_INVOICE_STATUSES
        exempt_statuses = (Invoice.STATUS_DRAFT,) + tuple(DEAD_INVOICE_STATUSES)
        for li in InvoiceLineItem.objects.select_related('invoice').exclude(
            invoice__status__in=exempt_statuses
        ).filter(accounting_category_id__isnull=True):
            self.errors.append(
                f'InvoiceLineItem {li.pk}: no accounting_category but invoice '
                f'{li.invoice.display_number} status is "{li.invoice.status}" '
                f'(past the send-time categorization gate)'
            )

    # ── Purchase Orders ───────────────────────────────────────

    def check_purchase_orders(self):
        from apps.purchasing.models import PurchaseOrder
        valid_statuses = {s[0] for s in PurchaseOrder.PO_STATUS_CHOICES}

        for po in PurchaseOrder.objects.select_related('business', 'contact').all():
            if po.status not in valid_statuses:
                self.errors.append(f'PO {po.po_number}: invalid status "{po.status}"')

            # Contact must have a business
            if po.contact and not po.contact.business_id:
                self.errors.append(f'PO {po.po_number}: contact has no business')

            # Issued POs should have issued_date
            if po.status != PurchaseOrder.STATUS_DRAFT and not po.issued_date:
                self.warnings.append(f'PO {po.po_number}: status is {po.status} but no issued_date')

            # Received POs should have received_date
            if po.status == PurchaseOrder.STATUS_RECEIVED_IN_FULL and not po.received_date:
                self.warnings.append(f'PO {po.po_number}: received_in_full but no received_date')

            # Cancelled POs should have cancel_date
            if po.status == PurchaseOrder.STATUS_CANCELLED and not po.cancel_date:
                self.warnings.append(f'PO {po.po_number}: cancelled but no cancel_date')

    # ── Invoices ──────────────────────────────────────────────

    def check_invoices(self):
        from apps.invoicing.models import Invoice
        valid_statuses = {s[0] for s in Invoice.INVOICE_STATUS_CHOICES}
        for inv in Invoice.objects.all():
            if inv.status not in valid_statuses:
                self.errors.append(f'Invoice {inv.invoice_number}: invalid status "{inv.status}"')

    # ── Service Prices ────────────────────────────────────────

    def check_rate_schemes(self):
        from apps.jobs.models import RateScheme
        valid_algorithms = {a[0] for a in RateScheme.ALGORITHM_CHOICES}
        for rs in RateScheme.objects.select_related('accounting_category').all():
            if rs.algorithm not in valid_algorithms:
                self.errors.append(
                    f'RateScheme {rs.pk} ({rs.name}): invalid algorithm "{rs.algorithm}"'
                )
            if not rs.accounting_category_id:
                self.errors.append(
                    f'RateScheme {rs.pk} ({rs.name}): missing accounting_category'
                )
            if rs.algorithm != RateScheme.PERCENTAGE and rs.rate is not None and rs.rate < 0:
                self.errors.append(
                    f'RateScheme {rs.pk} ({rs.name}): negative rate not allowed for {rs.algorithm}'
                )
            if rs.algorithm == RateScheme.ELAPSED_TIME and rs.unit_label != HOUR_UNIT:
                self.errors.append(
                    f'RateScheme {rs.pk} ({rs.name}): elapsed_time scheme must have '
                    f'unit_label "{HOUR_UNIT}", got "{rs.unit_label}"'
                )

    # ── Deliverables ──────────────────────────────────────────

    def check_deliverables(self):
        from apps.deliverables.models import Deliverable
        for d in Deliverable.objects.select_related('job').all():
            if not d.job_id:
                self.errors.append(f'Deliverable {d.pk}: not attached to a Job')
            if d.qty_ordered is None or d.qty_ordered <= 0:
                self.errors.append(
                    f'Deliverable {d.pk}: qty_ordered must be positive (got {d.qty_ordered})'
                )
            if not d.units or not d.units.strip():
                self.warnings.append(f'Deliverable {d.pk}: missing units')

    # ── Shipments ─────────────────────────────────────────────

    def check_shipments(self):
        from apps.deliverables.models import Shipment
        from apps.estimates.models import Estimate
        valid_statuses = {s[0] for s in Shipment.STATUS_CHOICES}
        for s in Shipment.objects.select_related('job').all():
            if s.status not in valid_statuses:
                self.errors.append(f'Shipment {s.pk}: invalid status "{s.status}"')
            # picked_up requires a picked_up_date; prepared must not have one
            if s.status == Shipment.STATUS_PICKED_UP and not s.picked_up_date:
                self.errors.append(f'Shipment {s.pk}: picked_up but no picked_up_date')
            if s.status == Shipment.STATUS_PREPARED and s.picked_up_date:
                self.errors.append(f'Shipment {s.pk}: prepared but picked_up_date is set')
            # A shipment should only exist once the job has an accepted estimate
            if s.job_id and not Estimate.objects.filter(
                    job_id=s.job_id, status=Estimate.STATUS_ACCEPTED).exists():
                self.warnings.append(
                    f'Shipment {s.pk}: job {s.job_id} has no accepted estimate'
                )

    # ── Shipment Items ────────────────────────────────────────

    def check_shipment_items(self):
        from collections import defaultdict
        from apps.deliverables.models import ShipmentItem, Deliverable
        shipped = defaultdict(Decimal)
        for si in ShipmentItem.objects.select_related('deliverable').all():
            if si.qty is None or si.qty <= 0:
                self.errors.append(
                    f'ShipmentItem {si.pk}: qty must be positive (got {si.qty})'
                )
            if si.deliverable_id:
                shipped[si.deliverable_id] += si.qty or Decimal('0')
        # Total shipped per deliverable must not exceed its ordered quantity
        for deliverable_id, total in shipped.items():
            d = Deliverable.objects.filter(pk=deliverable_id).first()
            if d and total > d.qty_ordered:
                self.errors.append(
                    f'Deliverable {deliverable_id}: shipped qty {total} exceeds '
                    f'qty_ordered {d.qty_ordered}'
                )

    # ── Price List Items ──────────────────────────────────────

    def check_inventory_items(self):
        from apps.inventory.models import InventoryItem
        for pli in InventoryItem.objects.all():
            if not pli.accounting_category_id:
                self.errors.append(
                    f'PLI {pli.code}: missing accounting_category '
                    f'(should not be possible — field is required)'
                )
            if pli.purchase_price < 0:
                self.errors.append(f'PLI {pli.code}: negative purchase_price {pli.purchase_price}')
            if pli.selling_price < 0:
                self.errors.append(f'PLI {pli.code}: negative selling_price {pli.selling_price}')
            if pli.qty_on_hand < 0:
                self.errors.append(f'PLI {pli.code}: negative qty_on_hand {pli.qty_on_hand}')
            if pli.qty_sold < 0:
                self.errors.append(f'PLI {pli.code}: negative qty_sold {pli.qty_sold}')
            if pli.qty_wasted < 0:
                self.errors.append(f'PLI {pli.code}: negative qty_wasted {pli.qty_wasted}')
            # (Universal tracking: every item carries quantities — no
            # "non-inventoried but has quantity" warning anymore.)
            # Duplicate codes
        codes = list(
            InventoryItem.objects.values_list('code', flat=True)
        )
        seen = set()
        for code in codes:
            if code in seen:
                self.errors.append(f'PLI: duplicate code "{code}"')
            seen.add(code)

    # ── Earmarks ──────────────────────────────────────────────

    def check_earmarks(self):
        from apps.inventory.models import Earmark
        for em in Earmark.objects.select_related('inventory_item', 'job').all():
            if em.quantity <= 0:
                self.errors.append(
                    f'Earmark {em.pk}: non-positive quantity {em.quantity}'
                )
            # (Universal tracking: earmarks apply to every item — no
            # "earmark on non-inventoried item" error anymore.)
            if em.quantity > em.inventory_item.qty_on_hand:
                self.warnings.append(
                    f'Earmark {em.pk}: quantity {em.quantity} exceeds QOH '
                    f'{em.inventory_item.qty_on_hand} for {em.inventory_item.code}'
                )

    # ══════════════════════════════════════════════════════════
    # Cross-model relationship invariants
    # ══════════════════════════════════════════════════════════

    def check_estimate_versioning(self):
        """Estimates sharing an estimate_number form a version chain.
        Higher versions must supersede lower ones (lower versions should
        be in 'superseded' status). The unique_together on
        (estimate_number, version) is DB-enforced, but the status
        invariant is not."""
        from apps.estimates.models import Estimate
        from collections import defaultdict

        # Group estimates by estimate_number
        by_number = defaultdict(list)
        for e in Estimate.objects.all().order_by('version'):
            by_number[e.estimate_number].append(e)

        for est_number, versions in by_number.items():
            if len(versions) < 2:
                continue

            max_version = max(v.version for v in versions)
            for e in versions:
                # All versions below the max should be superseded
                if e.version < max_version and e.status != Estimate.STATUS_SUPERSEDED:
                    self.errors.append(
                        f'Estimate {e.estimate_number} v{e.version}: '
                        f'superseded by v{max_version} but status is "{e.status}" (should be "superseded")'
                    )

            # Parent chain: each version's parent should be the previous version
            versions_sorted = sorted(versions, key=lambda e: e.version)
            for i in range(1, len(versions_sorted)):
                child = versions_sorted[i]
                expected_parent = versions_sorted[i - 1]
                if child.parent_id and child.parent_id != expected_parent.pk:
                    self.warnings.append(
                        f'Estimate {child.estimate_number} v{child.version}: '
                        f'parent is estimate pk={child.parent_id}, '
                        f'expected v{expected_parent.version} (pk={expected_parent.pk})'
                    )

    def check_job_estimate_status_alignment(self):
        """Job status and estimate status should be consistent.
        - Job 'approved' must have exactly one accepted estimate.
        - Job 'completed' should have an accepted estimate (warning — older
          jobs may predate the estimate workflow).
        - Job 'draft'/'submitted' should not have an accepted estimate.
        - Accepted estimate's job should be 'approved' or later
          (completed/cancelled are OK - job progressed past approval).
        - Completed/cancelled jobs should not have draft/open estimates."""
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate

        for job in Job.objects.all():
            accepted = Estimate.objects.filter(job=job, status=Estimate.STATUS_ACCEPTED)
            accepted_count = accepted.count()

            if job.status == Job.STATUS_APPROVED:
                if accepted_count == 0:
                    self.errors.append(
                        f'Job {job.job_number}: status is "approved" but has no accepted estimate'
                    )
            elif job.status in (Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED):
                if accepted_count == 0:
                    self.warnings.append(
                        f'Job {job.job_number}: status is "{job.status}" but has no accepted estimate'
                    )
            elif job.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED):
                if accepted_count > 0:
                    self.errors.append(
                        f'Job {job.job_number}: status is "{job.status}" but has '
                        f'{accepted_count} accepted estimate(s)'
                    )

            # Check from estimate side: accepted estimate's job should be approved+
            for e in accepted:
                if job.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_REJECTED):
                    self.errors.append(
                        f'Estimate {e.estimate_number} v{e.version}: accepted but '
                        f'job {job.job_number} status is "{job.status}"'
                    )

            # Open estimate's job must be submitted+ — when an estimate is sent
            # (draft → open), the signal moves a draft job to submitted. If we see
            # an open estimate on a draft or rejected job, the data is inconsistent.
            for e in Estimate.objects.filter(job=job, status=Estimate.STATUS_OPEN):
                if job.status in (Job.STATUS_DRAFT, Job.STATUS_REJECTED):
                    self.errors.append(
                        f'Estimate {e.estimate_number} v{e.version}: status is open but '
                        f'job {job.job_number} status is "{job.status}" '
                        f'(should be submitted+ once an estimate is sent)'
                    )

            # Completed/cancelled jobs should not have unresolved estimates
            if job.status in (Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED, Job.STATUS_CANCELLED):
                unresolved = Estimate.objects.filter(
                    job=job, status__in=(Estimate.STATUS_DRAFT, Estimate.STATUS_OPEN)
                )
                for e in unresolved:
                    self.errors.append(
                        f'Estimate {e.estimate_number} v{e.version}: status is "{e.status}" '
                        f'but job {job.job_number} is "{job.status}"'
                    )

    def check_po_contact_business_match(self):
        """If a PO has both contact and business, contact's business must match."""
        from apps.purchasing.models import PurchaseOrder

        for po in PurchaseOrder.objects.select_related('contact__business', 'business').filter(
            contact__isnull=False
        ):
            if po.contact.business_id and po.contact.business_id != po.business_id:
                self.errors.append(
                    f'PO {po.po_number}: contact belongs to business '
                    f'"{po.contact.business}" but PO is for "{po.business}"'
                )

    def check_earmark_job_status(self):
        """Earmarks for completed/cancelled/rejected jobs are suspicious -
        inventory should have been consumed or released."""
        from apps.inventory.models import Earmark

        for em in Earmark.objects.select_related('job', 'inventory_item').all():
            if em.job.status in (Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED, Job.STATUS_CANCELLED, Job.STATUS_REJECTED):
                self.warnings.append(
                    f'Earmark {em.pk}: {em.inventory_item.code} earmarked for '
                    f'job {em.job.job_number} which is "{em.job.status}"'
                )

    def check_invoice_job_status(self):
        """Invoices may only exist for jobs that have been approved or later —
        the app enforces this (`BILLABLE_JOB_STATUSES` guards every invoice
        creation path), so a draft/submitted/rejected job with an invoice is an
        unreachable state: an ERROR (upgraded from a warning 2026-07-12).
        A cancelled job may have invoices (work done before cancellation is
        billable)."""
        from apps.invoicing.models import Invoice

        for inv in Invoice.objects.select_related('job').all():
            if inv.job.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_REJECTED):
                self.errors.append(
                    f'Invoice {inv.invoice_number}: job {inv.job.job_number} '
                    f'status is "{inv.job.status}" (expected approved or later)'
                )

    def check_job_work_complete_gate(self):
        """work_complete (and completed) means every task terminal and every
        material resolved — JobService.update_job enforces this on every path
        into the status (the B4 work-complete gate, 2026-07-12), so a closed
        job with open work is an unreachable state."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material

        closed = (Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED)
        for t in Task.objects.select_related('job').filter(
            job__status__in=closed,
        ).exclude(status__in=(Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)):
            self.errors.append(
                f'Task {t.pk} ({t.name}): non-terminal task ("{t.status}") on '
                f'{t.job.status} job {t.job.job_number}'
            )
        for m in Material.objects.select_related('job').filter(
            job__status__in=closed,
            consumption_state=Material.CONSUMPTION_STATE_PENDING,
            quantity__gt=0,
        ):
            self.errors.append(
                f'Material {m.pk} ({m.description}): pending material with '
                f'quantity {m.quantity} on {m.job.status} job {m.job.job_number}'
            )

    def check_estimate_source_job_consistency(self):
        """For each EstimateLineItemSource (task/material), the atom's job_id
        must match the owning estimate's job_id."""
        from apps.estimates.models import EstimateLineItemSource
        atom_source_types = {
            EstimateLineItemSource.SOURCE_TASK,
            EstimateLineItemSource.SOURCE_MATERIAL,
        }
        for source in EstimateLineItemSource.objects.select_related(
            'estimate_line_item__estimate__job'
        ).filter(source_type__in=atom_source_types):
            estimate_job_id = source.estimate_line_item.estimate.job_id
            try:
                atom = source.resolve()
            except Exception:
                self.errors.append(
                    f'EstimateLineItemSource {source.pk} '
                    f'({source.source_type}:{source.source_pk}): atom not found'
                )
                continue
            atom_job_id = getattr(atom, 'job_id', None)
            if atom_job_id != estimate_job_id:
                self.errors.append(
                    f'EstimateLineItemSource {source.pk} '
                    f'({source.source_type}:{source.source_pk}): '
                    f'atom job_id={atom_job_id} does not match estimate job_id={estimate_job_id}'
                )

    def check_invoice_source_job_consistency(self):
        """For each InvoiceLineItemSource (task/material), the atom's job_id
        must match the owning invoice's job_id."""
        from apps.invoicing.models import InvoiceLineItemSource
        atom_source_types = {
            InvoiceLineItemSource.SOURCE_TASK,
            InvoiceLineItemSource.SOURCE_MATERIAL,
        }
        for source in InvoiceLineItemSource.objects.select_related(
            'invoice_line_item__invoice__job'
        ).filter(source_type__in=atom_source_types):
            invoice_job_id = source.invoice_line_item.invoice.job_id
            try:
                atom = source.resolve()
            except Exception:
                self.errors.append(
                    f'InvoiceLineItemSource {source.pk} '
                    f'({source.source_type}:{source.source_pk}): atom not found'
                )
                continue
            atom_job_id = getattr(atom, 'job_id', None)
            if atom_job_id != invoice_job_id:
                self.errors.append(
                    f'InvoiceLineItemSource {source.pk} '
                    f'({source.source_type}:{source.source_pk}): '
                    f'atom job_id={atom_job_id} does not match invoice job_id={invoice_job_id}'
                )
            # Terminal — not complete — is the task billability line (C3,
            # 2026-07-12): only complete/cancelled tasks may back an invoice
            # line.
            from apps.jobs.models import Task
            if (source.source_type == InvoiceLineItemSource.SOURCE_TASK
                    and isinstance(atom, Task)
                    and atom.status not in (Task.STATUS_COMPLETE,
                                            Task.STATUS_CANCELLED)):
                self.errors.append(
                    f'InvoiceLineItemSource {source.pk} (task:{source.source_pk}): '
                    f'task status "{atom.status}" is not billable '
                    f'(terminal statuses only)'
                )

    def check_agreement_line_invoice_exclusivity(self):
        """Each estimate line and change-order line may be referenced by at
        most one live invoice. A live invoice is every status except cancelled.
        Uses DB-side aggregation to identify violations, then fetches details only
        for violating IDs.

        Two distinct violation shapes are possible and get distinct
        messages: the agreement line is held by more than one DISTINCT live
        invoice (the invariant this check exists for), or it has more than
        one live InvoiceLineItem row all pointing at the same single
        invoice (duplicate references — also invalid, but not "more than
        one invoice" and would otherwise be misreported as such since a
        raw row-count doesn't distinguish the two)."""
        from apps.invoicing.models import InvoiceLineItem

        self._check_agreement_line_field_exclusivity(
            InvoiceLineItem, 'agreement_estimate_line_id', 'EstimateLineItem')
        self._check_agreement_line_field_exclusivity(
            InvoiceLineItem, 'agreement_co_line_id', 'ChangeOrderLineItem')

    def _check_agreement_line_field_exclusivity(self, InvoiceLineItem, field, label):
        # Aggregate at DB level: both a raw row count (n) and a distinct-
        # invoice count (n_invoices) — two dup rows on ONE invoice must not
        # be reported as "more than one live invoice".
        violations = InvoiceLineItem.objects.exclude(
            invoice__status=Invoice.STATUS_CANCELLED
        ).exclude(
            **{f'{field}__isnull': True}
        ).values(field).annotate(
            n=Count('pk'), n_invoices=Count('invoice', distinct=True),
        ).filter(n__gt=1)

        for v in violations:
            line_id = v[field]
            ilis = InvoiceLineItem.objects.exclude(
                invoice__status=Invoice.STATUS_CANCELLED
            ).filter(
                **{field: line_id}
            ).select_related('invoice')

            display_numbers = sorted(set(ili.invoice.display_number for ili in ilis))
            if v['n_invoices'] > 1:
                self.errors.append(
                    f'{label} {line_id}: referenced by more than one live invoice: '
                    f'{", ".join(display_numbers)}'
                )
            else:
                self.errors.append(
                    f'{label} {line_id}: referenced by {v["n"]} line items on '
                    f'the same live invoice {display_numbers[0]} (duplicate '
                    f'references).'
                )
