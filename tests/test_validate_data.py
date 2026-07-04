from decimal import Decimal
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from apps.core.models import AccountingCategory
from apps.jobs.models import RateScheme, Job, Task, Fee
from apps.contacts.models import Contact
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.inventory.models import Material


class ValidateDataRateSchemeTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        self.contact = Contact.objects.create(first_name='Test', last_name='User')

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _make_sp(self, name='Sp', rate=Decimal('10.00'), algorithm=None):
        if algorithm is None:
            algorithm = RateScheme.ENTERED_QTY
        return RateScheme.objects.create(
            name=name, algorithm=algorithm,
            rate=rate, unit_label='each', accounting_category=self.ac,
        )

    def _make_job(self, number='J-VDT-001'):
        return Job.objects.create(
            job_number=number, name='Test Job', contact=self.contact,
        )

    # ── active_modifiers dict-shape checks ───────────────────────

    def test_flags_dict_active_modifiers_on_task(self):
        sp = self._make_sp(name='Sp-task')
        job = self._make_job('J-VDT-002')
        # Bypass full_clean to force a dict into the JSONField
        Task.objects.filter(pk=Task.objects.create(
            name='Bad task', job=job, rate_scheme=sp,
            active_modifiers=[],
        ).pk).update(active_modifiers={'key': 'val'})
        output = self._run()
        self.assertIn('active_modifiers', output.lower())

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
        RateScheme.objects.create(
            name='bad-elapsed', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('-5.00'), unit_label='hr', accounting_category=self.ac,
        )
        output = self._run()
        self.assertIn('bad-elapsed', output)
        self.assertIn('negative rate', output)

    def test_valid_list_active_modifiers_not_flagged(self):
        sp = self._make_sp(name='Sp-list')
        job = self._make_job('J-VDT-004')
        Task.objects.create(
            name='Good task', job=job, rate_scheme=sp,
            active_modifiers=['mod1'],
        )
        output = self._run()
        self.assertNotIn('active_modifiers', output.lower())


class ValidateDataFeeTest(TestCase):
    """Tests for check_fees() — unit_rate, quantity, accounting_category, task-job match."""

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

    def _make_rate_scheme(self, name='RS-Fee'):
        return RateScheme.objects.create(
            name=name, algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='each', accounting_category=self.ac,
        )

    # ── unit_rate ────────────────────────────────────────────────

    def test_fee_unit_rate_zero_is_error(self):
        self._make_fee(unit_rate=Decimal('0.00'))
        output = self._run()
        self.assertIn('unit_rate must be positive', output)

    def test_fee_unit_rate_negative_is_error(self):
        self._make_fee(unit_rate=Decimal('-5.00'))
        output = self._run()
        self.assertIn('unit_rate must be positive', output)

    def test_fee_positive_unit_rate_not_flagged(self):
        self._make_fee(unit_rate=Decimal('0.01'))
        output = self._run()
        self.assertNotIn('unit_rate must be positive', output)

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

    # ── task-job consistency ──────────────────────────────────────

    def test_fee_task_on_wrong_job_is_error(self):
        rs = self._make_rate_scheme()
        job_b = Job.objects.create(
            job_number='J-VFEE-002', name='Other Job', contact=self.contact,
        )
        task_b = Task.objects.create(name='Task on B', job=job_b, rate_scheme=rs)
        # fee.job = self.job (job_a), fee.task = task_b (on job_b) → mismatch
        self._make_fee(task=task_b)
        output = self._run()
        self.assertIn('but Fee belongs to job', output)

    def test_fee_task_on_same_job_not_flagged(self):
        rs = self._make_rate_scheme(name='RS-SameJob')
        task = Task.objects.create(name='Same-job Task', job=self.job, rate_scheme=rs)
        self._make_fee(task=task)
        output = self._run()
        self.assertNotIn('but Fee belongs to job', output)

    def test_valid_fee_produces_no_errors(self):
        self._make_fee()
        output = self._run()
        self.assertNotIn('unit_rate must be positive', output)
        self.assertNotIn('negative quantity', output)
        self.assertNotIn('missing accounting_category', output)
        self.assertNotIn('but Fee belongs to job', output)


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
        task_b = Task.objects.create(name='Task B', job=self.job_b, rate_scheme=self.rs)
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
        task_a = Task.objects.create(name='Task A', job=self.job_a, rate_scheme=self.rs)
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
        task_b = Task.objects.create(name='Inv Task B', job=self.job_b, rate_scheme=self.rs)
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
        task_a = Task.objects.create(name='Inv Task A', job=self.job_a, rate_scheme=self.rs)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.ili,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=task_a.pk,
        )
        output = self._run()
        self.assertNotIn('does not match invoice job_id', output)
        self.assertNotIn('atom not found', output)
