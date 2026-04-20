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
                   W  approved/completed/cancelled: missing start_date
                   W  completed/cancelled: missing completed_date
  Estimate         E  valid status value
                   E  max one accepted estimate per job
                   W  open: missing sent_date
                   W  accepted/rejected/superseded/expired: missing closed_date
  EstWorksheet     E  valid status value
  Task             E  must belong to a Job
                   E  must belong to an EstWorksheet
  Material         E  must have description or price_list_item
                   E  negative quantity
                   W  has PLI but empty description (--fix: auto-fill)
  LineItems        E  cannot have both task and price_list_item (mutual exclusivity)
  (all 4 types)    W  negative price
  PurchaseOrder    E  valid status value
                   E  contact must have a business
                   W  non-draft: missing issued_date
                   W  received_in_full: missing received_date
                   W  cancelled: missing cancel_date
  Bill             E  valid status value
                   E  contact must have a business
                   E  cannot link to draft PO
                   E  non-draft must have at least one line item
  Invoice          E  valid status value
  PriceListItem    E  missing accounting_category (causes silent tax-exemption)
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
                   E  completed/cancelled job must not have draft/open estimates
  Est/Worksheet    E  worksheet with linked estimate must be 'final' (not 'draft')
                   E  worksheet with superseded estimate must be 'superseded'
  Worksheet/Job    E  worksheet's job must match its linked estimate's job
  Worksheet ver.   E  parent version must be lower than child
                   E  parent must belong to same job
                   W  parent should be 'superseded'
  Bundle/Tasks     E  all tasks in a bundle must be on the bundle's container
  EstLineItem/Job  E  task-sourced line item's job must match estimate's job
  PO contact/biz   E  contact's business must match PO's business
  Bill/PO biz      E  bill's business must match linked PO's business
  Earmark/Job      W  earmark on completed/cancelled/rejected job
  Invoice/Job      W  invoice on draft/submitted/rejected job
                   E  cancelled job's invoices must also be cancelled
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db.models import Sum

from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstWorksheet
from apps.purchasing.models import PurchaseOrder, Bill
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
        self.check_estimates()
        self.check_worksheets()
        self.check_tasks()
        self.check_task_bundles()
        self.check_materials()
        self.check_line_items()
        self.check_purchase_orders()
        self.check_bills()
        self.check_invoices()
        self.check_price_list_items()
        self.check_earmarks()
        self.check_inventory_adjustments()

        # Cross-model relationship invariants
        self.check_estimate_versioning()
        self.check_job_estimate_status_alignment()
        self.check_estimate_worksheet_status_alignment()
        self.check_worksheet_job_consistency()
        self.check_worksheet_versioning()
        self.check_task_container_job_consistency()
        self.check_bundle_container_consistency()
        self.check_estimate_line_item_job_consistency()
        self.check_po_contact_business_match()
        self.check_bill_po_business_match()
        self.check_earmark_job_status()
        self.check_invoice_job_status()

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
            if j.status in (Job.STATUS_APPROVED, Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED, Job.STATUS_CANCELLED) and not j.start_date:
                self.warnings.append(f'Job {j.job_number}: status is {j.status} but no start_date')
            # Terminal states should have completed_date
            if j.status in (Job.STATUS_COMPLETED, Job.STATUS_CANCELLED) and not j.completed_date:
                self.warnings.append(f'Job {j.job_number}: status is {j.status} but no completed_date')

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

        # Only one accepted estimate per job
        for job in Job.objects.all():
            accepted_count = Estimate.objects.filter(job=job, status=Estimate.STATUS_ACCEPTED).count()
            if accepted_count > 1:
                self.errors.append(
                    f'Job {job.job_number}: has {accepted_count} accepted estimates (max 1)'
                )

    # ── Worksheets ────────────────────────────────────────────

    def check_worksheets(self):
        from apps.estimates.models import EstWorksheet
        valid_statuses = {s[0] for s in EstWorksheet.EST_WORKSHEET_STATUS_CHOICES}
        for ws in EstWorksheet.objects.all():
            if ws.status not in valid_statuses:
                self.errors.append(f'EstWorksheet {ws.pk}: invalid status "{ws.status}"')

    # ── Tasks ─────────────────────────────────────────────────

    def check_tasks(self):
        from apps.jobs.models import Task, PlanTask
        # Tasks now belong directly to a Job (post-WorkOrder-removal).
        for t in Task.objects.select_related('job').all():
            if not t.job_id:
                self.errors.append(f'Task {t.pk} ({t.name}): not attached to a Job')
        # Plan tasks: PlanTask is worksheet-only
        for t in PlanTask.objects.select_related('est_worksheet').all():
            if not t.est_worksheet_id:
                self.errors.append(f'PlanTask {t.pk} ({t.name}): not attached to an EstWorksheet')

    # ── Materials ─────────────────────────────────────────────

    def check_materials(self):
        from apps.inventory.models import Material, PlanMaterial
        # Check PlanMaterials (worksheet-side)
        for m in PlanMaterial.objects.select_related('price_list_item', 'plan_task').all():
            if not m.description and not m.price_list_item:
                self.errors.append(
                    f'PlanMaterial {m.pk}: no description and no price_list_item (nothing to derive from)'
                )
            if m.price_list_item and not m.description:
                if self.fix:
                    m.description = m.price_list_item.description[:255]
                    m.save()
                    self.fixes.append(f'PlanMaterial {m.pk}: set description from PLI')
                else:
                    self.warnings.append(f'PlanMaterial {m.pk}: has PLI but empty description')
            if m.quantity < 0:
                self.errors.append(f'PlanMaterial {m.pk}: negative quantity {m.quantity}')

        # Check Materials (work-order side)
        for m in Material.objects.select_related('price_list_item', 'task').all():
            if not m.description and not m.price_list_item:
                self.errors.append(
                    f'Material {m.pk}: no description and no price_list_item (nothing to derive from)'
                )
            # Auto-fill check: if PLI linked, description should match or be explicitly set
            if m.price_list_item and not m.description:
                if self.fix:
                    m.description = m.price_list_item.description[:255]
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
        from apps.purchasing.models import PurchaseOrderLineItem, BillLineItem

        # (name, model, has_task_fk) — InvoiceLineItem's task FK was dropped in
        # favour of InvoiceLineItemSource, so it can't be included in select_related.
        line_item_models = [
            ('EstimateLineItem', EstimateLineItem, True),
            ('InvoiceLineItem', InvoiceLineItem, False),
            ('PurchaseOrderLineItem', PurchaseOrderLineItem, True),
            ('BillLineItem', BillLineItem, True),
        ]

        for name, model, has_task_fk in line_item_models:
            if has_task_fk:
                qs = model.objects.select_related('task', 'price_list_item').all()
            else:
                qs = model.objects.select_related('price_list_item').all()
            for li in qs:
                # Mutual exclusivity: cannot have both task and price_list_item
                if li.task and li.price_list_item:
                    self.errors.append(
                        f'{name} {li.pk}: has both task and price_list_item (mutually exclusive)'
                    )
                # Negative price
                if li.price < 0:
                    self.warnings.append(f'{name} {li.pk}: negative price {li.price}')

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

    # ── Bills ─────────────────────────────────────────────────

    def check_bills(self):
        from apps.purchasing.models import Bill, BillLineItem
        valid_statuses = {s[0] for s in Bill.BILL_STATUS_CHOICES}

        for bill in Bill.objects.select_related('business', 'contact', 'purchase_order').all():
            if bill.status not in valid_statuses:
                self.errors.append(f'Bill {bill.bill_number}: invalid status "{bill.status}"')

            # Contact must have a business
            if bill.contact and not bill.contact.business_id:
                self.errors.append(f'Bill {bill.bill_number}: contact has no business')

            # Bill linked to draft PO
            if bill.purchase_order and bill.purchase_order.status == PurchaseOrder.STATUS_DRAFT:
                self.errors.append(
                    f'Bill {bill.bill_number}: linked to draft PO {bill.purchase_order.po_number}'
                )

            # Non-draft bills need at least one line item
            if bill.status != Bill.STATUS_DRAFT:
                if not BillLineItem.objects.filter(bill=bill).exists():
                    self.errors.append(
                        f'Bill {bill.bill_number}: status is {bill.status} but has no line items'
                    )

    # ── Invoices ──────────────────────────────────────────────

    def check_invoices(self):
        from apps.invoicing.models import Invoice
        valid_statuses = {s[0] for s in Invoice.INVOICE_STATUS_CHOICES}
        for inv in Invoice.objects.all():
            if inv.status not in valid_statuses:
                self.errors.append(f'Invoice {inv.invoice_number}: invalid status "{inv.status}"')

    # ── Price List Items ──────────────────────────────────────

    def check_price_list_items(self):
        from apps.inventory.models import PriceListItem
        for pli in PriceListItem.objects.all():
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
            # Non-inventoried items should have zero quantities
            if not pli.is_inventoried:
                if pli.qty_on_hand != 0 or pli.qty_sold != 0 or pli.qty_wasted != 0:
                    self.warnings.append(
                        f'PLI {pli.code}: not inventoried but has quantity values '
                        f'(qoh={pli.qty_on_hand}, sold={pli.qty_sold}, wasted={pli.qty_wasted})'
                    )
            # Duplicate codes
        codes = list(
            PriceListItem.objects.values_list('code', flat=True)
        )
        seen = set()
        for code in codes:
            if code in seen:
                self.errors.append(f'PLI: duplicate code "{code}"')
            seen.add(code)

    # ── Earmarks ──────────────────────────────────────────────

    def check_earmarks(self):
        from apps.inventory.models import Earmark
        for em in Earmark.objects.select_related('price_list_item', 'job').all():
            if em.quantity <= 0:
                self.errors.append(
                    f'Earmark {em.pk}: non-positive quantity {em.quantity}'
                )
            if not em.price_list_item.is_inventoried:
                self.errors.append(
                    f'Earmark {em.pk}: PLI {em.price_list_item.code} is not inventoried'
                )
            if em.quantity > em.price_list_item.qty_on_hand:
                self.warnings.append(
                    f'Earmark {em.pk}: quantity {em.quantity} exceeds QOH '
                    f'{em.price_list_item.qty_on_hand} for {em.price_list_item.code}'
                )

    # ── Inventory Adjustments ─────────────────────────────────

    def check_inventory_adjustments(self):
        from apps.inventory.models import InventoryAdjustment
        for adj in InventoryAdjustment.objects.select_related('price_list_item').all():
            if not adj.price_list_item.is_inventoried:
                self.warnings.append(
                    f'InventoryAdjustment {adj.pk}: PLI {adj.price_list_item.code} is not inventoried'
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

    def check_estimate_worksheet_status_alignment(self):
        """Worksheet status must be consistent with its linked estimate's status.

        Creating an estimate FROM a worksheet locks the worksheet to 'final'.
        So any worksheet with a linked estimate should be 'final' or 'superseded',
        never 'draft'.

        Rules:
        - estimate superseded -> worksheet must be superseded
        - any other estimate status -> worksheet must be final

        NOTE: the signal in Estimate._get_worksheet_status currently maps
        estimate 'draft' -> worksheet 'draft', which is a bug. The correct
        behavior is that generating an estimate locks the worksheet to 'final'.
        """
        from apps.estimates.models import EstWorksheet

        for ws in EstWorksheet.objects.select_related('estimate').filter(estimate__isnull=False):
            if ws.estimate.status == Estimate.STATUS_SUPERSEDED:
                if ws.status != EstWorksheet.STATUS_SUPERSEDED:
                    self.errors.append(
                        f'EstWorksheet {ws.pk} v{ws.version}: status is "{ws.status}" but '
                        f'linked estimate {ws.estimate.estimate_number} is superseded '
                        f'(worksheet should be "superseded")'
                    )
            else:
                if ws.status != EstWorksheet.STATUS_FINAL:
                    self.errors.append(
                        f'EstWorksheet {ws.pk} v{ws.version}: status is "{ws.status}" but '
                        f'has linked estimate {ws.estimate.estimate_number} '
                        f'(worksheet should be "final" once an estimate is generated from it)'
                    )

    def check_worksheet_job_consistency(self):
        """Worksheet's job must match its estimate's job (if estimate is linked)."""
        from apps.estimates.models import EstWorksheet

        for ws in EstWorksheet.objects.select_related('estimate', 'job').filter(estimate__isnull=False):
            if ws.job_id != ws.estimate.job_id:
                self.errors.append(
                    f'EstWorksheet {ws.pk}: job is {ws.job_id} but '
                    f'linked estimate {ws.estimate.estimate_number} belongs to job {ws.estimate.job_id}'
                )

    def check_worksheet_versioning(self):
        """Worksheet version chains: parent worksheet should have lower version,
        and superseded worksheets should have a child or be the result of
        explicit supersession."""
        from apps.estimates.models import EstWorksheet

        for ws in EstWorksheet.objects.select_related('parent').filter(parent__isnull=False):
            if ws.parent.version >= ws.version:
                self.errors.append(
                    f'EstWorksheet {ws.pk} v{ws.version}: parent is v{ws.parent.version} '
                    f'(parent version should be lower)'
                )
            if ws.parent.status != EstWorksheet.STATUS_SUPERSEDED:
                self.warnings.append(
                    f'EstWorksheet {ws.pk} v{ws.version}: parent (pk={ws.parent.pk}) '
                    f'status is "{ws.parent.status}" (expected "superseded")'
                )
            # Parent should belong to same job
            if ws.parent.job_id != ws.job_id:
                self.errors.append(
                    f'EstWorksheet {ws.pk}: job is {ws.job_id} but '
                    f'parent worksheet belongs to job {ws.parent.job_id}'
                )

    def check_estimate_line_item_job_consistency(self):
        """EstimateLineItems with a task source: the task's worksheet should
        belong to the same job as the estimate."""
        from apps.estimates.models import EstimateLineItem

        for li in EstimateLineItem.objects.select_related(
            'estimate__job', 'task__est_worksheet__job'
        ).filter(task__isnull=False):
            task_worksheet = li.task.est_worksheet
            if task_worksheet and task_worksheet.job_id != li.estimate.job_id:
                self.errors.append(
                    f'EstimateLineItem {li.pk}: estimate is for job {li.estimate.job_id} '
                    f'but plan task {li.task.pk} belongs to job {task_worksheet.job_id}'
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

    def check_bill_po_business_match(self):
        """If a bill is linked to a PO, both should reference the same business."""
        from apps.purchasing.models import Bill

        for bill in Bill.objects.select_related('purchase_order__business', 'business').filter(
            purchase_order__isnull=False
        ):
            if bill.business_id != bill.purchase_order.business_id:
                self.errors.append(
                    f'Bill {bill.bill_number}: business is "{bill.business}" '
                    f'but linked PO {bill.purchase_order.po_number} '
                    f'is for "{bill.purchase_order.business}"'
                )

    def check_earmark_job_status(self):
        """Earmarks for completed/cancelled/rejected jobs are suspicious -
        inventory should have been consumed or released."""
        from apps.inventory.models import Earmark

        for em in Earmark.objects.select_related('job', 'price_list_item').all():
            if em.job.status in (Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED, Job.STATUS_CANCELLED, Job.STATUS_REJECTED):
                self.warnings.append(
                    f'Earmark {em.pk}: {em.price_list_item.code} earmarked for '
                    f'job {em.job.job_number} which is "{em.job.status}"'
                )

    def check_invoice_job_status(self):
        """Invoices should only exist for jobs that have been approved or later.
        A draft/submitted/rejected job shouldn't have invoices.
        A cancelled job can have invoices, but they must also be cancelled."""
        from apps.invoicing.models import Invoice

        for inv in Invoice.objects.select_related('job').all():
            if inv.job.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_REJECTED):
                self.warnings.append(
                    f'Invoice {inv.invoice_number}: job {inv.job.job_number} '
                    f'status is "{inv.job.status}" (expected approved or later)'
                )
            elif inv.job.status == Job.STATUS_CANCELLED and inv.status != Invoice.STATUS_CANCELLED:
                self.errors.append(
                    f'Invoice {inv.invoice_number}: job {inv.job.job_number} '
                    f'is cancelled but invoice status is "{inv.status}" (should be cancelled)'
                )
