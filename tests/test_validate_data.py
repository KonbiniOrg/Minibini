from decimal import Decimal
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from django.utils import timezone
from apps.core.models import AccountingCategory, User
from apps.jobs.models import RateScheme, Job, Task, Fee
from apps.contacts.models import Contact
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstimateLineItemSource,
    ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource, ServiceItem,
)
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.inventory.models import Material, InventoryItem


def _task_scheme_fields(scheme):
    """Copy a RateScheme preset's money fields onto Task-creation kwargs,
    mirroring Task.stamp_from_scheme (task-owned-money Phase 1). Tests that
    build a Task directly via Task.objects.create() use this instead of the
    old Task.rate_scheme FK, which was renamed to the provenance-only
    source_scheme plus the task's own qty_source/rate/unit_label/
    accounting_category fields."""
    return dict(
        source_scheme=scheme,
        qty_source=scheme.algorithm,
        rate=scheme.rate,
        unit_label=scheme.unit_label,
        accounting_category=scheme.accounting_category,
    )


class ValidateDataRateSchemeTest(TestCase):
    """Tests for check_rate_schemes() — algorithm, accounting_category,
    negative-rate-only-for-percentage, elapsed_time hour-pin. RateScheme is
    a freely-editable preset now (task-owned-money Phase 1, Task 4):
    supersession/frozen-field assertions are gone, not moved here."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        self.contact = Contact.objects.create(first_name='Test', last_name='User')

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _make_sp(self, name='Sp', rate=Decimal('10.00'), algorithm=None, unit_label='each'):
        if algorithm is None:
            algorithm = RateScheme.ENTERED_QTY
        return RateScheme.objects.create(
            name=name, algorithm=algorithm,
            rate=rate, unit_label=unit_label, accounting_category=self.ac,
        )

    # ── Negative rate / percentage checks ───────────────────────

    def test_negative_rate_only_allowed_for_percentage(self):
        """A percentage RateScheme with a negative rate (discount) is OK."""
        RateScheme.objects.create(
            name='disc', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('-10'), unit_label='%', accounting_category=self.ac,
        )
        output = self._run()
        self.assertNotIn('disc', output)

    def test_negative_rate_non_percentage_is_flagged(self):
        """A non-percentage RateScheme with a negative rate is an error."""
        # clean() forbids a negative rate on a non-percentage scheme, so a
        # normal .create() can't plant this. Create valid, then bypass
        # full_clean via QuerySet.update() to simulate legacy bad data.
        scheme = RateScheme.objects.create(
            name='bad-elapsed', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('5.00'), unit_label='hour', accounting_category=self.ac,
        )
        RateScheme.objects.filter(pk=scheme.pk).update(rate=Decimal('-5.00'))
        output = self._run()
        self.assertIn('bad-elapsed', output)
        self.assertIn('negative rate', output)

    # ── elapsed_time hour-pin ─────────────────────────────────────

    def test_elapsed_time_scheme_wrong_unit_label_is_flagged(self):
        """clean() pins elapsed_time schemes to 'hour'; bypass it via
        QuerySet.update() to simulate legacy/corrupt fixture data."""
        scheme = self._make_sp(name='bad-unit', algorithm=RateScheme.ELAPSED_TIME, unit_label='hour')
        RateScheme.objects.filter(pk=scheme.pk).update(unit_label='each')
        output = self._run()
        self.assertIn('bad-unit', output)
        self.assertIn('must have unit_label "hour"', output)

    def test_elapsed_time_scheme_hour_unit_not_flagged(self):
        self._make_sp(name='good-elapsed', algorithm=RateScheme.ELAPSED_TIME, unit_label='hour')
        output = self._run()
        self.assertNotIn('good-elapsed', output)

    def test_entered_qty_scheme_non_hour_unit_not_flagged(self):
        """The hour-pin only applies to elapsed_time; other algorithms are free."""
        self._make_sp(name='good-entered', algorithm=RateScheme.ENTERED_QTY, unit_label='each')
        output = self._run()
        self.assertNotIn('good-entered', output)


class ValidateDataTaskMoneyTest(TestCase):
    """Tests for the check_tasks() task-owned-money checks (task-owned-money
    Phase 1, Task 9; accounting_category nullability relaxed in Phase 3,
    Task 2): qty_source in choices, non-negative rate, and the
    active_modifiers {key, percent}-dict shape (a Task's own snapshot,
    unlike ServiceItem.default_active_modifiers, which stays a plain
    key-list)."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        self.contact = Contact.objects.create(first_name='Test', last_name='User')

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _make_sp(self, name='Sp', rate=Decimal('10.00'), algorithm=None,
                 unit_label='each', modifiers=None):
        if algorithm is None:
            algorithm = RateScheme.ENTERED_QTY
        return RateScheme.objects.create(
            name=name, algorithm=algorithm, rate=rate, unit_label=unit_label,
            accounting_category=self.ac, modifiers=modifiers or [],
        )

    def _make_job(self, number='J-VDT-001'):
        return Job.objects.create(
            job_number=number, name='Test Job', contact=self.contact,
        )

    def _make_task(self, job, scheme, name='Task', modifier_keys=None):
        """Build a Task via the real stamping path (Task.stamp_from_scheme)
        so its money fields have the shape production code actually
        produces."""
        task = Task(name=name, job=job)
        task.stamp_from_scheme(scheme, modifier_keys=modifier_keys)
        task.save()
        return task

    # ── active_modifiers {key, percent}-dict shape ────────────────

    def test_flags_dict_active_modifiers_on_task(self):
        sp = self._make_sp(name='Sp-task')
        job = self._make_job('J-VDT-002')
        task = self._make_task(job, sp, name='Bad task')
        # Bypass full_clean to force a dict into the JSONField
        Task.objects.filter(pk=task.pk).update(active_modifiers={'key': 'val'})
        output = self._run()
        self.assertIn('active_modifiers', output.lower())
        self.assertIn('Bad task', output)

    def test_flags_string_entry_in_active_modifiers(self):
        sp = self._make_sp(name='Sp-str')
        job = self._make_job('J-VDT-003')
        task = self._make_task(job, sp, name='String-entry task')
        Task.objects.filter(pk=task.pk).update(active_modifiers=['rush'])
        output = self._run()
        self.assertIn('is not', output)
        self.assertIn('String-entry task', output)

    def test_flags_bare_dict_missing_key_and_percent(self):
        sp = self._make_sp(name='Sp-bare')
        job = self._make_job('J-VDT-005')
        task = self._make_task(job, sp, name='Bare-dict task')
        Task.objects.filter(pk=task.pk).update(active_modifiers=[{'label': 'Rush'}])
        output = self._run()
        self.assertIn('missing key', output)
        self.assertIn('percent must be numeric', output)
        self.assertIn('Bare-dict task', output)

    def test_valid_active_modifiers_dict_list_not_flagged(self):
        sp = self._make_sp(
            name='Sp-list',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 10}],
        )
        job = self._make_job('J-VDT-006')
        self._make_task(job, sp, name='Good task', modifier_keys=['rush'])
        output = self._run()
        self.assertNotIn('active_modifiers', output.lower())

    def test_empty_active_modifiers_not_flagged(self):
        sp = self._make_sp(name='Sp-empty')
        job = self._make_job('J-VDT-007')
        self._make_task(job, sp, name='No-modifiers task')
        output = self._run()
        self.assertNotIn('active_modifiers', output.lower())

    # ── ServiceItem.default_active_modifiers stays a key-list ─────

    def test_flags_dict_default_active_modifiers_on_service_item(self):
        from apps.estimates.models import ServiceItem
        sp = self._make_sp(name='Sp-tt')
        tt = ServiceItem.objects.create(
            template_name='Bad Template',
            rate_scheme=sp,
            default_active_modifiers=[],
        )
        ServiceItem.objects.filter(pk=tt.pk).update(default_active_modifiers={'key': 'val'})
        output = self._run()
        self.assertIn('default_active_modifiers', output.lower())

    def test_valid_list_default_active_modifiers_on_service_item_not_flagged(self):
        from apps.estimates.models import ServiceItem
        sp = self._make_sp(name='Sp-tt-good')
        ServiceItem.objects.create(
            template_name='Good Template',
            rate_scheme=sp,
            default_active_modifiers=['mod1'],
        )
        output = self._run()
        self.assertNotIn('default_active_modifiers', output.lower())

    # ── qty_source ──────────────────────────────────────────────

    def test_invalid_qty_source_is_flagged(self):
        sp = self._make_sp(name='Sp-qty')
        job = self._make_job('J-VDT-008')
        task = self._make_task(job, sp, name='Bad qty_source task')
        Task.objects.filter(pk=task.pk).update(qty_source='bogus')
        output = self._run()
        self.assertIn('invalid qty_source', output)
        self.assertIn('Bad qty_source task', output)

    def test_valid_qty_source_not_flagged(self):
        sp = self._make_sp(name='Sp-qty-ok', algorithm=RateScheme.ELAPSED_TIME, unit_label='hour')
        job = self._make_job('J-VDT-009')
        self._make_task(job, sp, name='Good qty_source task')
        output = self._run()
        self.assertNotIn('invalid qty_source', output)

    # ── rate ────────────────────────────────────────────────────

    def test_negative_rate_on_task_is_flagged(self):
        sp = self._make_sp(name='Sp-rate')
        job = self._make_job('J-VDT-010')
        task = self._make_task(job, sp, name='Negative-rate task')
        Task.objects.filter(pk=task.pk).update(rate=Decimal('-5.00'))
        output = self._run()
        self.assertIn('negative rate', output)
        self.assertIn('Negative-rate task', output)

    def test_positive_rate_on_task_not_flagged(self):
        sp = self._make_sp(name='Sp-rate-ok')
        job = self._make_job('J-VDT-011')
        self._make_task(job, sp, name='Positive-rate task')
        output = self._run()
        self.assertNotIn('negative rate', output)

    # ── accounting_category ────────────────────────────────────
    # Nullable end-to-end as of task-owned-money Phase 3, Task 2: a
    # manual/flat task may legitimately carry no AC ("categorize at
    # invoicing" — the invoice compose fallback, Phase 3 Task 3), so a null
    # value here is clean, not an error.

    def test_null_accounting_category_on_task_not_flagged(self):
        sp = self._make_sp(name='Sp-ac')
        job = self._make_job('J-VDT-012')
        task = self._make_task(job, sp, name='No-AC task')
        Task.objects.filter(pk=task.pk).update(accounting_category=None)
        output = self._run()
        self.assertNotIn('accounting_category', output)

    def test_present_accounting_category_not_flagged(self):
        sp = self._make_sp(name='Sp-ac-ok')
        job = self._make_job('J-VDT-013')
        self._make_task(job, sp, name='Has-AC task')
        output = self._run()
        self.assertNotIn('missing accounting_category', output)

    # ── source_scheme: SET_NULL orphaning is legal, no check ──────

    def test_deleted_source_scheme_is_not_flagged(self):
        """Deleting a RateScheme SET_NULLs every Task.source_scheme that
        stamped from it — provenance-only, so this must never be an error."""
        sp = self._make_sp(name='Sp-deleteme')
        job = self._make_job('J-VDT-014')
        task = self._make_task(job, sp, name='Orphaned task')
        sp.delete()
        task.refresh_from_db()
        self.assertIsNone(task.source_scheme_id)
        output = self._run()
        self.assertNotIn('source_scheme', output)
        self.assertNotIn('Orphaned task', output)


class ValidateDataFeeTest(TestCase):
    """Tests for check_fees() — unit_rate, quantity, accounting_category."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='FeeSvc', code='FSVC')
        self.contact = Contact.objects.create(first_name='Fee', last_name='Tester')
        self.job = Job.objects.create(
            job_number='J-VFEE-001', name='Fee Job', contact=self.contact,
        )

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _make_fee(self, **kwargs):
        defaults = dict(
            job=self.job,
            description='Test Fee',
            quantity=Decimal('1.00'),
            unit_rate=Decimal('100.00'),
            accounting_category=self.ac,
        )
        defaults.update(kwargs)
        return Fee.objects.create(**defaults)

    # ── unit_rate ────────────────────────────────────────────────

    def test_fee_unit_rate_zero_is_error(self):
        self._make_fee(unit_rate=Decimal('0.00'))
        output = self._run()
        self.assertIn('unit_rate must not be zero', output)

    def test_fee_unit_rate_negative_not_flagged(self):
        """A credit is a negative Fee — negative unit_rate is valid."""
        self._make_fee(unit_rate=Decimal('-5.00'))
        output = self._run()
        self.assertNotIn('unit_rate must not be zero', output)

    def test_fee_positive_unit_rate_not_flagged(self):
        self._make_fee(unit_rate=Decimal('0.01'))
        output = self._run()
        self.assertNotIn('unit_rate must not be zero', output)

    # ── accounting_category ──────────────────────────────────────

    # ── quantity ─────────────────────────────────────────────────

    def test_fee_negative_quantity_is_error(self):
        self._make_fee(quantity=Decimal('-1.00'))
        output = self._run()
        self.assertIn('negative quantity', output)

    def test_fee_zero_quantity_not_flagged(self):
        """quantity=0 is allowed (check is quantity < 0, not quantity <= 0)."""
        self._make_fee(quantity=Decimal('0.00'))
        output = self._run()
        self.assertNotIn('negative quantity', output)

    def test_valid_fee_produces_no_errors(self):
        self._make_fee()
        output = self._run()
        self.assertNotIn('unit_rate must not be zero', output)
        self.assertNotIn('negative quantity', output)
        self.assertNotIn('missing accounting_category', output)


class ValidateDataSourceJobConsistencyTest(TestCase):
    """Tests for check_estimate_source_job_consistency() and
    check_invoice_source_job_consistency() — atom's job must match
    the owning document's job."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='SrcSvc', code='SRCSVC')
        self.contact = Contact.objects.create(first_name='Src', last_name='Tester')
        self.rs = RateScheme.objects.create(
            name='RS-Src', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='each', accounting_category=self.ac,
        )
        self.job_a = Job.objects.create(
            job_number='J-VSRC-001', name='Job A', contact=self.contact,
        )
        self.job_b = Job.objects.create(
            job_number='J-VSRC-002', name='Job B', contact=self.contact,
        )
        # Estimate on job_a
        self.estimate = Estimate.objects.create(
            job=self.job_a,
            estimate_number='EST-VSRC-001',
            version=1,
        )
        self.eli = EstimateLineItem.objects.create(estimate=self.estimate)
        # Invoice on job_a
        self.invoice = Invoice.objects.create(
            job=self.job_a,
            invoice_number='INV-VSRC-001',
        )
        self.ili = InvoiceLineItem.objects.create(invoice=self.invoice)

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    # ── EstimateLineItemSource cross-checks ──────────────────────

    def test_estimate_source_task_wrong_job_is_error(self):
        task_b = Task.objects.create(name='Task B', job=self.job_b, **_task_scheme_fields(self.rs))
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.eli,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task_b.pk,
        )
        output = self._run()
        self.assertIn('EstimateLineItemSource', output)
        self.assertIn('does not match estimate job_id', output)

    def test_estimate_source_material_wrong_job_is_error(self):
        mat_b = Material.objects.create(
            job=self.job_b, description='Mat B', accounting_category=self.ac,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.eli,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=mat_b.pk,
        )
        output = self._run()
        self.assertIn('EstimateLineItemSource', output)
        self.assertIn('does not match estimate job_id', output)

    def test_estimate_source_fee_wrong_job_is_error(self):
        fee_b = Fee.objects.create(
            job=self.job_b, description='Fee B',
            unit_rate=Decimal('50.00'), accounting_category=self.ac,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.eli,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=fee_b.pk,
        )
        output = self._run()
        self.assertIn('EstimateLineItemSource', output)
        self.assertIn('does not match estimate job_id', output)

    def test_estimate_source_dangling_atom_is_error(self):
        """If the source_pk doesn't resolve to an atom, it should be flagged."""
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.eli,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=999999,
        )
        output = self._run()
        self.assertIn('EstimateLineItemSource', output)
        self.assertIn('atom not found', output)

    def test_estimate_source_task_same_job_not_flagged(self):
        task_a = Task.objects.create(name='Task A', job=self.job_a, **_task_scheme_fields(self.rs))
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.eli,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task_a.pk,
        )
        output = self._run()
        self.assertNotIn('does not match estimate job_id', output)
        self.assertNotIn('atom not found', output)

    # ── InvoiceLineItemSource cross-checks ───────────────────────

    def test_invoice_source_task_wrong_job_is_error(self):
        task_b = Task.objects.create(name='Inv Task B', job=self.job_b, **_task_scheme_fields(self.rs))
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.ili,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=task_b.pk,
        )
        output = self._run()
        self.assertIn('InvoiceLineItemSource', output)
        self.assertIn('does not match invoice job_id', output)

    def test_invoice_source_material_wrong_job_is_error(self):
        mat_b = Material.objects.create(
            job=self.job_b, description='Inv Mat B', accounting_category=self.ac,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.ili,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
            source_pk=mat_b.pk,
        )
        output = self._run()
        self.assertIn('InvoiceLineItemSource', output)
        self.assertIn('does not match invoice job_id', output)

    def test_invoice_source_fee_wrong_job_is_error(self):
        fee_b = Fee.objects.create(
            job=self.job_b, description='Inv Fee B',
            unit_rate=Decimal('75.00'), accounting_category=self.ac,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.ili,
            source_type=InvoiceLineItemSource.SOURCE_FEE,
            source_pk=fee_b.pk,
        )
        output = self._run()
        self.assertIn('InvoiceLineItemSource', output)
        self.assertIn('does not match invoice job_id', output)

    def test_invoice_source_dangling_atom_is_error(self):
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.ili,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
            source_pk=999999,
        )
        output = self._run()
        self.assertIn('InvoiceLineItemSource', output)
        self.assertIn('atom not found', output)

    def test_invoice_source_task_same_job_not_flagged(self):
        task_a = Task.objects.create(name='Inv Task A', job=self.job_a, **_task_scheme_fields(self.rs))
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.ili,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=task_a.pk,
        )
        output = self._run()
        self.assertNotIn('does not match invoice job_id', output)
        self.assertNotIn('atom not found', output)


class ValidateDataStateInvariantsTest(TestCase):
    """2026-07-12 tasks-refinements invariants: invoice-on-unapproved-job is
    an ERROR (was a warning), work_complete/completed jobs carry only final
    work, subtasks are one level deep, and invoice sources only point at
    terminal (billable) tasks."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Inv', code='INVAR')
        self.contact = Contact.objects.create(first_name='St', last_name='Inv')
        self.rs = RateScheme.objects.create(
            name='RS-Invar', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'), unit_label='hour', accounting_category=self.ac,
        )

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _job(self, number, status=None):
        job = Job.objects.create(
            job_number=number, name='Invariant Job', contact=self.contact,
        )
        if status:
            Job.objects.filter(pk=job.pk).update(status=status)
            job.refresh_from_db()
        return job

    def _task(self, job, status=Task.STATUS_PENDING, parent=None, name='T'):
        task = Task.objects.create(
            name=name, job=job, parent_task=parent, **_task_scheme_fields(self.rs),
        )
        if status != Task.STATUS_PENDING:
            Task.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
        return task

    # ── invoice on an unapproved job is an ERROR ─────────────────

    def test_invoice_on_draft_job_is_an_error(self):
        job = self._job('J-VST-001')
        Invoice.objects.create(job=job, invoice_number='INV-VST-001')
        output = self._run()
        line = next(l for l in output.splitlines()
                    if 'expected approved or later' in l)
        self.assertIn('[ERROR]', line)

    def test_invoice_on_approved_job_not_flagged(self):
        job = self._job('J-VST-002', status=Job.STATUS_APPROVED)
        Invoice.objects.create(job=job, invoice_number='INV-VST-002')
        output = self._run()
        self.assertNotIn('expected approved or later', output)

    # ── work-complete gate (B4) ──────────────────────────────────

    def test_pending_task_on_work_complete_job_is_an_error(self):
        job = self._job('J-VST-003', status=Job.STATUS_WORK_COMPLETE)
        self._task(job, status=Task.STATUS_PENDING)
        output = self._run()
        self.assertIn('[ERROR]', output)
        self.assertIn('non-terminal task', output)

    def test_terminal_tasks_on_work_complete_job_not_flagged(self):
        job = self._job('J-VST-004', status=Job.STATUS_WORK_COMPLETE)
        self._task(job, status=Task.STATUS_COMPLETE)
        self._task(job, status=Task.STATUS_CANCELLED, name='T2')
        output = self._run()
        self.assertNotIn('non-terminal task', output)

    def test_pending_material_on_completed_job_is_an_error(self):
        job = self._job('J-VST-005', status=Job.STATUS_COMPLETED)
        Material.objects.create(
            job=job, description='Leftover', quantity=Decimal('2.00'),
            accounting_category=self.ac,
        )
        output = self._run()
        self.assertIn('[ERROR]', output)
        self.assertIn('pending material', output)

    def test_consumed_material_on_completed_job_not_flagged(self):
        job = self._job('J-VST-006', status=Job.STATUS_COMPLETED)
        Material.objects.create(
            job=job, description='Used up', quantity=Decimal('2.00'),
            accounting_category=self.ac,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )
        output = self._run()
        self.assertNotIn('pending material', output)

    # ── one level of subtasks ────────────────────────────────────

    def test_grandchild_task_is_an_error(self):
        job = self._job('J-VST-007')
        parent = self._task(job, name='Parent')
        child = self._task(job, parent=parent, name='Child')
        self._task(job, parent=child, name='Grandchild')
        output = self._run()
        self.assertIn('[ERROR]', output)
        self.assertIn('subtask of a subtask', output)

    def test_one_level_subtask_not_flagged(self):
        job = self._job('J-VST-008')
        parent = self._task(job, name='Parent')
        self._task(job, parent=parent, name='Child')
        output = self._run()
        self.assertNotIn('subtask of a subtask', output)

    # ── invoice sources bill only terminal tasks ─────────────────

    def _invoice_source_for(self, task, number):
        invoice = Invoice.objects.create(job=task.job, invoice_number=number)
        ili = InvoiceLineItem.objects.create(invoice=invoice)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ili,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )

    def test_invoice_source_on_pending_task_is_an_error(self):
        job = self._job('J-VST-009', status=Job.STATUS_IN_PROGRESS)
        task = self._task(job, status=Task.STATUS_PENDING)
        self._invoice_source_for(task, 'INV-VST-009')
        output = self._run()
        self.assertIn('[ERROR]', output)
        self.assertIn('not billable', output)

    def test_invoice_source_on_terminal_tasks_not_flagged(self):
        # One invoice, two lines: complete AND cancelled tasks both bill
        # (terminal is the billability line). Two invoices won't do — only
        # one draft invoice may exist per job.
        job = self._job('J-VST-010', status=Job.STATUS_IN_PROGRESS)
        done = self._task(job, status=Task.STATUS_COMPLETE)
        killed = self._task(job, status=Task.STATUS_CANCELLED, name='K')
        invoice = Invoice.objects.create(job=job, invoice_number='INV-VST-010')
        for task in (done, killed):
            ili = InvoiceLineItem.objects.create(invoice=invoice)
            InvoiceLineItemSource.objects.create(
                invoice_line_item=ili,
                source_type=InvoiceLineItemSource.SOURCE_TASK,
                source_pk=task.pk,
            )
        output = self._run()
        self.assertNotIn('not billable', output)


class ValidateDataFreeformKindConsistencyTest(TestCase):
    """Tests for check_freeform_kind_consistency() — freeform_kind must be
    null on any EstimateLineItem/ChangeOrderLineItem that is NOT bare (i.e.
    has an inventory_item, service_item, or — EstimateLineItem only —
    adjustment_service). The invariant is enforced only at the service
    layer (EstimateService._reject_freeform_kind_on_non_bare_line), not by
    a model clean() guard, so plant violations via QuerySet.update() to
    bypass the service, matching the file's established pattern."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='FKSvc', code='FKSVC')
        self.contact = Contact.objects.create(first_name='FK', last_name='Tester')
        self.job = Job.objects.create(
            job_number='J-VFK-001', name='FK Job', contact=self.contact,
        )
        self.rs = RateScheme.objects.create(
            name='RS-FK', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='each', accounting_category=self.ac,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-VFK-001', version=1,
        )
        self.pli = InventoryItem.objects.create(code='FK-ITEM', accounting_category=self.ac)
        self.service_item = ServiceItem.objects.create(
            template_name='FK Service', rate_scheme=self.rs,
        )

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    # ── EstimateLineItem ──────────────────────────────────────────

    def test_estimate_line_freeform_kind_with_inventory_item_is_error(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, inventory_item=self.pli,
        )
        EstimateLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        output = self._run()
        self.assertIn(f'EstimateLineItem {li.pk}', output)
        self.assertIn('freeform_kind', output)
        self.assertIn('not bare', output)

    def test_estimate_line_freeform_kind_with_service_item_is_error(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, service_item=self.service_item,
        )
        EstimateLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        output = self._run()
        self.assertIn(f'EstimateLineItem {li.pk}', output)
        self.assertIn('freeform_kind', output)
        self.assertIn('not bare', output)

    def test_estimate_line_freeform_kind_with_adjustment_service_is_error(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, adjustment_service=self.rs,
            adjustment_percent=Decimal('-10.00'),
        )
        EstimateLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=EstimateLineItem.KIND_MATERIAL,
        )
        output = self._run()
        self.assertIn(f'EstimateLineItem {li.pk}', output)
        self.assertIn('freeform_kind', output)
        self.assertIn('not bare', output)

    def test_estimate_line_freeform_kind_bare_not_flagged(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate,
        )
        EstimateLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        output = self._run()
        self.assertNotIn('not bare', output)

    def test_estimate_line_no_freeform_kind_with_inventory_item_not_flagged(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, inventory_item=self.pli,
        )
        output = self._run()
        self.assertNotIn('not bare', output)

    def test_estimate_line_bare_with_null_freeform_kind_is_error(self):
        """The inverse: a bare line (no inventory_item/service_item/
        adjustment_service) whose freeform_kind is NULL. Reachable via an
        InventoryItem delete or merge that SET_NULLs a CO line's
        inventory_item without repointing/rejecting it first — planted here
        via QuerySet.update() since a normal .create() already lands here by
        default (no service-layer guard runs on it), matching the file's
        established bypass pattern for the other branch."""
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, inventory_item=self.pli,
        )
        EstimateLineItem.objects.filter(pk=li.pk).update(inventory_item=None)
        output = self._run()
        self.assertIn(f'EstimateLineItem {li.pk}', output)
        self.assertIn('freeform_kind', output)
        self.assertIn('null on a bare line', output)

    def test_estimate_line_bare_with_kind_set_not_flagged_as_null(self):
        li = EstimateLineItem.objects.create(estimate=self.estimate)
        EstimateLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        output = self._run()
        self.assertNotIn('null on a bare line', output)

    def test_estimate_line_wizard_sourced_bare_null_kind_not_flagged(self):
        """A wizard-composed line (add_atoms_to_new_line_item): no
        inventory_item/service_item/adjustment_service AND freeform_kind is
        NULL — looks identical to the corruption state above by FK/kind
        alone, but it claims an atom via EstimateLineItemSource, so it is
        not freeform at all and must never be flagged by either direction
        of the check. This is real, common shape on live data (Critical
        review finding), not a corner case."""
        fee = Fee.objects.create(
            job=self.job, description='Sourced Fee',
            unit_rate=Decimal('50.00'), accounting_category=self.ac,
        )
        li = EstimateLineItem.objects.create(estimate=self.estimate)
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=fee.pk,
        )
        output = self._run()
        self.assertNotIn('null on a bare line', output)
        self.assertNotIn('not bare', output)

    # ── ChangeOrderLineItem ───────────────────────────────────────

    def _make_co(self):
        return ChangeOrder.objects.create(job=self.job, estimate=self.estimate)

    def test_co_line_freeform_kind_with_inventory_item_is_error(self):
        co = self._make_co()
        li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            inventory_item=self.pli,
        )
        ChangeOrderLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=ChangeOrderLineItem.KIND_FEE,
        )
        output = self._run()
        self.assertIn(f'ChangeOrderLineItem {li.pk}', output)
        self.assertIn('freeform_kind', output)
        self.assertIn('not bare', output)

    def test_co_line_freeform_kind_with_service_item_is_error(self):
        co = self._make_co()
        li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            service_item=self.service_item,
        )
        ChangeOrderLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=ChangeOrderLineItem.KIND_WORK,
        )
        output = self._run()
        self.assertIn(f'ChangeOrderLineItem {li.pk}', output)
        self.assertIn('freeform_kind', output)
        self.assertIn('not bare', output)

    def test_co_line_freeform_kind_bare_not_flagged(self):
        co = self._make_co()
        li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
        )
        ChangeOrderLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=ChangeOrderLineItem.KIND_MATERIAL,
        )
        output = self._run()
        self.assertNotIn('not bare', output)

    def test_co_line_bare_with_null_freeform_kind_is_error(self):
        """The inverse on the CO side — this is the exact shape of the
        gap named in the check's docstring: InventoryItem delete
        (assert_item_deletable never checks ChangeOrderLineItem refs) or
        merge (repoints every other FK-holder but not ChangeOrderLineItem)
        SET_NULLs inventory_item, leaving a bare line with freeform_kind
        still NULL."""
        co = self._make_co()
        li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            inventory_item=self.pli,
        )
        ChangeOrderLineItem.objects.filter(pk=li.pk).update(inventory_item=None)
        output = self._run()
        self.assertIn(f'ChangeOrderLineItem {li.pk}', output)
        self.assertIn('freeform_kind', output)
        self.assertIn('null on a bare line', output)

    def test_co_line_bare_with_kind_set_not_flagged_as_null(self):
        co = self._make_co()
        li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
        )
        ChangeOrderLineItem.objects.filter(pk=li.pk).update(
            freeform_kind=ChangeOrderLineItem.KIND_MATERIAL,
        )
        output = self._run()
        self.assertNotIn('null on a bare line', output)

    def test_co_line_wizard_sourced_bare_null_kind_not_flagged(self):
        """CO-side analog of the wizard-sourced EstimateLineItem test: a
        line with no FKs and NULL freeform_kind, but claiming an atom via
        ChangeOrderLineItemSource (created at CO acceptance for each
        add/replace line) — not freeform, must not be flagged by either
        direction."""
        co = self._make_co()
        fee = Fee.objects.create(
            job=self.job, description='CO Sourced Fee',
            unit_rate=Decimal('75.00'), accounting_category=self.ac,
        )
        li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
        )
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=li,
            source_type=ChangeOrderLineItemSource.SOURCE_FEE,
            source_pk=fee.pk,
        )
        output = self._run()
        self.assertNotIn('null on a bare line', output)
        self.assertNotIn('not bare', output)

    # ── C1 seam tests: forward is FK-only, inverse is bare+unsourced ──

    def test_accepted_estimate_all_three_hand_line_kinds_is_clean(self):
        """CRITICAL review finding (C1), seam test (a): an accepted
        estimate's claimed bare hand-lines (freeform_kind set at entry,
        PLUS a self-pointing EstimateLineItemSource added by acceptance)
        must not be flagged. Under the old is_bare = no-FK-and-no-source
        definition, acceptance's source row alone flipped these lines to
        "not bare" and falsely errored on their retained (legal) kind."""
        from apps.estimates.acceptance import EstimateAcceptanceService

        job = Job.objects.create(
            job_number='J-VFK-ACC', name='FK Accept Job', contact=self.contact,
        )
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-VFK-ACC', version=1,
            status=Estimate.STATUS_OPEN,
        )
        EstimateLineItem.objects.create(
            estimate=estimate, line_number=1, description='Raw stock',
            qty=Decimal('2'), price=Decimal('40.00'), units='ft',
            accounting_category=self.ac, freeform_kind=EstimateLineItem.KIND_MATERIAL,
        )
        EstimateLineItem.objects.create(
            estimate=estimate, line_number=2, description='Custom fitting',
            qty=Decimal('3'), price=Decimal('50.00'), units='ea',
            accounting_category=self.ac, freeform_kind=EstimateLineItem.KIND_WORK,
        )
        EstimateLineItem.objects.create(
            estimate=estimate, line_number=3, description='Rush handling',
            qty=Decimal('1'), price=Decimal('25.00'),
            accounting_category=self.ac, freeform_kind=EstimateLineItem.KIND_FEE,
        )

        EstimateAcceptanceService.on_accept(estimate)

        output = self._run()
        self.assertNotIn('freeform_kind', output)


class ValidateDataEstimateHandLineCategorizationTest(TestCase):
    """Tests for check_estimate_hand_line_categorization() (Phase 3 Task 7):
    a hand-line (no atom source, not a percentage adjustment) missing an
    accounting_category is a WARNING while the estimate is still draft
    (legitimate pre-send state, or a bypass of the write-time service
    guard), and an ERROR once the estimate has left draft (the send-time
    gate — EstimateService.assert_all_hand_lines_have_ac — must already
    have passed, so the state is unreachable through normal means)."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='EHLC', code='EHLC')
        self.contact = Contact.objects.create(first_name='Ehl', last_name='Cee')
        self.job = Job.objects.create(
            job_number='J-EHLC-001', name='EHLC Job', contact=self.contact,
        )
        self.rs = RateScheme.objects.create(
            name='RS-EHLC', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='each', accounting_category=self.ac,
        )

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _estimate(self, status=Estimate.STATUS_DRAFT, number='EST-EHLC-001'):
        return Estimate.objects.create(
            job=self.job, estimate_number=number, version=1, status=status,
        )

    def test_draft_hand_line_missing_ac_is_warning(self):
        estimate = self._estimate()
        li = EstimateLineItem.objects.create(
            estimate=estimate, line_number=1, description='No-cat charge',
            qty=Decimal('1'), price=Decimal('10.00'),
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        output = self._run()
        line = next(l for l in output.splitlines() if f'EstimateLineItem {li.pk}' in l)
        self.assertIn('[WARN]', line)
        self.assertIn('hand-line has no accounting_category', line)

    def test_open_hand_line_missing_ac_is_error(self):
        estimate = self._estimate(status=Estimate.STATUS_OPEN, number='EST-EHLC-002')
        li = EstimateLineItem.objects.create(
            estimate=estimate, line_number=1, description='No-cat charge',
            qty=Decimal('1'), price=Decimal('10.00'),
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        output = self._run()
        line = next(l for l in output.splitlines() if f'EstimateLineItem {li.pk}' in l)
        self.assertIn('[ERROR]', line)
        self.assertIn('hand-line has no accounting_category', line)
        self.assertIn('past the send-time AC gate', line)

    def test_hand_line_with_ac_not_flagged(self):
        estimate = self._estimate(number='EST-EHLC-003')
        li = EstimateLineItem.objects.create(
            estimate=estimate, line_number=1, description='Categorized charge',
            qty=Decimal('1'), price=Decimal('10.00'), accounting_category=self.ac,
            freeform_kind=EstimateLineItem.KIND_FEE,
        )
        output = self._run()
        self.assertNotIn(f'EstimateLineItem {li.pk}', output)

    def test_atom_backed_line_missing_ac_not_flagged(self):
        """A line with an EstimateLineItemSource row is atom-backed, not a
        hand-line — exempt regardless of AC, same as
        EstimateService.assert_all_hand_lines_have_ac."""
        estimate = self._estimate(status=Estimate.STATUS_OPEN, number='EST-EHLC-004')
        task = Task.objects.create(name='T', job=self.job, **_task_scheme_fields(self.rs))
        li = EstimateLineItem.objects.create(
            estimate=estimate, line_number=1, description='Setup labor',
            qty=Decimal('2'), price=Decimal('200.00'),
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        output = self._run()
        self.assertNotIn(f'EstimateLineItem {li.pk}', output)

    def test_adjustment_line_missing_ac_not_flagged(self):
        """An adjustment line (adjustment_service set) is exempt regardless
        of AC, same as EstimateService.assert_all_hand_lines_have_ac."""
        estimate = self._estimate(status=Estimate.STATUS_OPEN, number='EST-EHLC-005')
        adj_scheme = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.ac,
        )
        li = EstimateLineItem.objects.create(
            estimate=estimate, line_number=1, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'),
            adjustment_service=adj_scheme, adjustment_percent=adj_scheme.rate,
        )
        output = self._run()
        self.assertNotIn(f'EstimateLineItem {li.pk}', output)


class ValidateDataInvoiceLineCategorizationTest(TestCase):
    """Tests for check_invoice_line_categorization() (Phase 3 Task 7): an
    InvoiceLineItem missing an accounting_category is a WARNING while the
    invoice is still draft (compose always stamps a category — the live gap
    is a freeform line added directly via the API, bypassing the frontend's
    client-side check), and an ERROR once the invoice has left draft (the
    send-time gate — InvoiceEmailService._assert_all_lines_categorized —
    must already have passed, so the state is unreachable through normal
    means)."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='IHLC', code='IHLC')
        self.contact = Contact.objects.create(first_name='Ihl', last_name='Cee')
        self.job = Job.objects.create(
            job_number='J-IHLC-001', name='IHLC Job', contact=self.contact,
        )

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _invoice(self, status=Invoice.STATUS_DRAFT, number='INV-IHLC-001'):
        return Invoice.objects.create(
            job=self.job, invoice_number=number, status=status,
        )

    def test_draft_line_missing_ac_is_warning(self):
        invoice = self._invoice()
        li = InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, description='No-cat charge',
            qty=Decimal('1'), price=Decimal('10.00'),
        )
        output = self._run()
        line = next(l for l in output.splitlines() if f'InvoiceLineItem {li.pk}' in l)
        self.assertIn('[WARN]', line)
        self.assertIn('no accounting_category', line)

    def test_open_line_missing_ac_is_error(self):
        invoice = self._invoice(status=Invoice.STATUS_OPEN, number='INV-IHLC-002')
        li = InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, description='No-cat charge',
            qty=Decimal('1'), price=Decimal('10.00'),
        )
        output = self._run()
        line = next(l for l in output.splitlines() if f'InvoiceLineItem {li.pk}' in l)
        self.assertIn('[ERROR]', line)
        self.assertIn('no accounting_category', line)
        self.assertIn('past the send-time AC gate', line)

    def test_line_with_ac_not_flagged(self):
        invoice = self._invoice(number='INV-IHLC-003')
        li = InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, description='Categorized charge',
            qty=Decimal('1'), price=Decimal('10.00'), accounting_category=self.ac,
        )
        output = self._run()
        self.assertNotIn(f'InvoiceLineItem {li.pk}', output)


class ValidateDataNegativePriceFeeExemptionTest(TestCase):
    """check_line_items() (M1 review finding): a negative price is
    legitimate on a fee/credit line — bare freeform_kind='fee' hand-lines,
    or lines claiming/sourced from a Fee atom via SOURCE_FEE — and must not
    warn. Everything else (bare work lines, PO lines) still warns."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='FeeNeg', code='FEENEG')
        self.contact = Contact.objects.create(first_name='Neg', last_name='Tester')
        self.job = Job.objects.create(
            job_number='J-NEGFEE-001', name='Neg Fee Job', contact=self.contact,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-NEGFEE-001', version=1,
        )

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def test_bare_fee_kind_negative_price_not_warned(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Credit',
            qty=Decimal('1'), price=Decimal('-25.00'),
            accounting_category=self.ac, freeform_kind=EstimateLineItem.KIND_FEE,
        )
        output = self._run()
        self.assertNotIn(f'EstimateLineItem {li.pk}: negative price', output)

    def test_invoice_line_sourced_from_fee_negative_price_not_warned(self):
        fee = Fee.objects.create(
            job=self.job, description='Sourced Credit',
            unit_rate=Decimal('-40.00'), accounting_category=self.ac,
        )
        invoice = Invoice.objects.create(job=self.job, invoice_number='INV-NEGFEE-001')
        ili = InvoiceLineItem.objects.create(
            invoice=invoice, line_number=1, description='Sourced Credit',
            qty=Decimal('1'), price=Decimal('-40.00'),
            accounting_category=self.ac,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ili,
            source_type=InvoiceLineItemSource.SOURCE_FEE,
            source_pk=fee.pk,
        )
        output = self._run()
        self.assertNotIn(f'InvoiceLineItem {ili.pk}: negative price', output)

    def test_bare_work_kind_negative_price_still_warned(self):
        """Control: the exemption is scoped to fee-kind/fee-sourced lines
        only — a bare work line with a negative price (a data mistake, not
        legitimately billable) still warns."""
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Bad work line',
            qty=Decimal('1'), price=Decimal('-10.00'),
            accounting_category=self.ac, freeform_kind=EstimateLineItem.KIND_WORK,
        )
        output = self._run()
        self.assertIn(f'EstimateLineItem {li.pk}: negative price', output)


class ValidateDataSubtaskBillingInvariantTest(TestCase):
    """Tests for check_subtask_billing_invariant() (task-owned-money Phase 4
    Task 6): a subtask (Task with parent_task set) never bills independently
    — the parent is the sole unit of billing (spec §9 rule 5). The wizard
    pool builders already exclude parent_task_id-set tasks from being
    claimable, so a source row on one can only arise via a bypass path;
    planted directly here (a plain .create() on the source join table has
    no guard against this — the exclusion lives in the pool builder, not a
    model/service check on the source table itself), matching the file's
    established pattern of exercising invariants the service layer doesn't
    reach."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='SubBill', code='SUBBILL')
        self.contact = Contact.objects.create(first_name='Sub', last_name='Bill')
        self.job = Job.objects.create(
            job_number='J-VSB-001', name='Subtask Billing Job', contact=self.contact,
        )
        self.rs = RateScheme.objects.create(
            name='RS-SubBill', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='each', accounting_category=self.ac,
        )
        self.parent = Task.objects.create(
            name='Parent', job=self.job, **_task_scheme_fields(self.rs),
        )
        self.child = Task.objects.create(
            name='Child', job=self.job, parent_task=self.parent,
            **_task_scheme_fields(self.rs),
        )

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def test_estimate_source_on_subtask_is_error(self):
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-VSB-001', version=1,
        )
        li = EstimateLineItem.objects.create(estimate=estimate)
        source = EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.child.pk,
        )
        output = self._run()
        line = next(l for l in output.splitlines()
                    if f'EstimateLineItemSource {source.pk}' in l)
        self.assertIn('[ERROR]', line)
        self.assertIn('subtask', line)
        self.assertIn('never bill independently', line)

    def test_change_order_source_on_subtask_is_error(self):
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-VSB-002', version=1,
        )
        co = ChangeOrder.objects.create(job=self.job, estimate=estimate)
        co_li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
        )
        source = ChangeOrderLineItemSource.objects.create(
            change_order_line_item=co_li,
            source_type=ChangeOrderLineItemSource.SOURCE_TASK,
            source_pk=self.child.pk,
        )
        output = self._run()
        line = next(l for l in output.splitlines()
                    if f'ChangeOrderLineItemSource {source.pk}' in l)
        self.assertIn('[ERROR]', line)
        self.assertIn('subtask', line)

    def test_invoice_source_on_subtask_is_error(self):
        # Terminal status so the unrelated "not billable" check
        # (check_invoice_source_job_consistency) doesn't also fire on this
        # same source row and shadow the assertion below.
        Task.objects.filter(pk=self.child.pk).update(status=Task.STATUS_COMPLETE)
        invoice = Invoice.objects.create(job=self.job, invoice_number='INV-VSB-001')
        ili = InvoiceLineItem.objects.create(invoice=invoice)
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=ili,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.child.pk,
        )
        output = self._run()
        line = next(l for l in output.splitlines()
                    if f'InvoiceLineItemSource {source.pk}' in l)
        self.assertIn('[ERROR]', line)
        self.assertIn('subtask', line)

    def test_estimate_source_on_top_level_task_not_flagged(self):
        """Clean path: a top-level (parentless) task claimed as usual is
        exactly what pools are supposed to allow — never flagged."""
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-VSB-003', version=1,
        )
        li = EstimateLineItem.objects.create(estimate=estimate)
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.parent.pk,
        )
        output = self._run()
        self.assertNotIn('never bill independently', output)


class ValidateDataParentBlepTest(TestCase):
    """Tests for the parent-task-with-own-bleps WARN (task-owned-money
    Phase 4 Task 6): a parent (≥1 subtask) is non-startable going forward
    (spec §9 rule 1), so a NEW blep can't land on it — but a blep logged
    BEFORE the task grew its first subtask is legitimate history the gate
    can't retroactively erase. Tolerated as WARN, not ERROR."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='ParBlep', code='PARBLEP')
        self.contact = Contact.objects.create(first_name='Par', last_name='Blep')
        self.job = Job.objects.create(
            job_number='J-VPB-001', name='Parent Blep Job', contact=self.contact,
        )
        self.rs = RateScheme.objects.create(
            name='RS-ParBlep', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('30.00'), unit_label='hour', accounting_category=self.ac,
        )
        self.user = User.objects.create_user(username='parblep-worker', password='x')

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _task(self, status=Task.STATUS_IN_PROGRESS, parent=None, name='T'):
        task = Task.objects.create(
            name=name, job=self.job, parent_task=parent,
            **_task_scheme_fields(self.rs),
        )
        if status != Task.STATUS_PENDING:
            Task.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
        return task

    def test_parent_with_own_blep_is_warned(self):
        from apps.jobs.models import Blep
        parent = self._task(name='Parent')
        self._task(parent=parent, name='Child')
        # Open blep (no end_time) — avoids tripping the unrelated
        # enclosure check, which only applies to closed bleps.
        Blep.objects.create(task=parent, user=self.user, start_time=timezone.now())
        output = self._run()
        line = next(l for l in output.splitlines()
                    if f'Task {parent.pk}' in l and 'own blep' in l)
        self.assertIn('[WARN]', line)
        self.assertIn('pre-parenthood history', line)

    def test_childless_task_with_blep_not_flagged(self):
        from apps.jobs.models import Blep
        solo = self._task(name='Solo')
        Blep.objects.create(task=solo, user=self.user, start_time=timezone.now())
        output = self._run()
        self.assertNotIn('own blep', output)

    def test_child_task_with_blep_not_flagged_as_parent(self):
        """The subtask itself carrying a blep is normal — only the PARENT
        carrying its own blep is the tolerated-historical case."""
        from apps.jobs.models import Blep
        parent = self._task(name='Parent')
        child = self._task(parent=parent, name='Child')
        Blep.objects.create(task=child, user=self.user, start_time=timezone.now())
        output = self._run()
        self.assertNotIn('own blep', output)


class ValidateDataParentAssigneeTest(TestCase):
    """Tests for the parent-task-with-own-assignee WARN (task-owned-money
    Phase 4 Task 6 review follow-up): a parent (≥1 subtask) is non-startable
    going forward (spec §9 rule 1) and TaskService.assign hard-rejects
    assigning one, but an assignee set BEFORE the task grew its first
    subtask is legitimate history the gate can't retroactively erase.
    Tolerated as WARN, not ERROR — mirrors ValidateDataParentBlepTest."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='ParAssign', code='PARASSIGN')
        self.contact = Contact.objects.create(first_name='Par', last_name='Assign')
        self.job = Job.objects.create(
            job_number='J-VPA-001', name='Parent Assignee Job', contact=self.contact,
        )
        self.rs = RateScheme.objects.create(
            name='RS-ParAssign', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('20.00'), unit_label='each', accounting_category=self.ac,
        )
        self.user = User.objects.create_user(username='parassign-worker', password='x')

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _task(self, parent=None, name='T', assignee=None):
        return Task.objects.create(
            name=name, job=self.job, parent_task=parent, assignee=assignee,
            **_task_scheme_fields(self.rs),
        )

    def test_parent_with_own_assignee_is_warned(self):
        # A direct .create() with assignee set is a legal model state
        # (TaskService.assign's parent-rejection is a service-layer guard,
        # not a model clean() check — no QuerySet.update() bypass needed).
        parent = self._task(name='Parent', assignee=self.user)
        self._task(parent=parent, name='Child')
        output = self._run()
        line = next(l for l in output.splitlines()
                    if f'Task {parent.pk}' in l and 'own assignee' in l)
        self.assertIn('[WARN]', line)
        self.assertIn('pre-parenthood history', line)

    def test_childless_task_with_assignee_not_flagged(self):
        self._task(name='Solo', assignee=self.user)
        output = self._run()
        self.assertNotIn('own assignee', output)

    def test_child_task_with_assignee_not_flagged_as_parent(self):
        """The subtask itself carrying an assignee is normal (assignment
        delegates to children) — only the PARENT carrying its own assignee
        is the tolerated-historical case."""
        parent = self._task(name='Parent')
        self._task(parent=parent, name='Child', assignee=self.user)
        output = self._run()
        self.assertNotIn('own assignee', output)
