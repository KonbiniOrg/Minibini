from decimal import Decimal
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from apps.core.models import AccountingCategory
from apps.jobs.models import ServiceItem, Job, Task, PlanTask
from apps.contacts.models import Contact
from apps.estimates.models import EstWorksheet


class ValidateDataServiceItemTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        self.contact = Contact.objects.create(first_name='Test', last_name='User')

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _make_sp(self, name='Sp', rate=Decimal('10.00'), algorithm=None):
        if algorithm is None:
            algorithm = ServiceItem.FLAT_FEE
        return ServiceItem.objects.create(
            name=name, algorithm=algorithm,
            rate=rate, unit_label='each', accounting_category=self.ac,
        )

    def _make_job(self, number='J-VDT-001'):
        return Job.objects.create(
            job_number=number, name='Test Job', contact=self.contact,
        )

    # ── Flat-fee rate checks ──────────────────────────────────────

    def test_flags_zero_rate_flat_fee(self):
        ServiceItem.objects.create(
            name='Bad flat', algorithm=ServiceItem.FLAT_FEE,
            rate=Decimal('0.00'), unit_label='each', accounting_category=self.ac,
        )
        output = self._run()
        self.assertIn('flat-fee', output.lower())

    def test_flags_negative_rate_flat_fee(self):
        ServiceItem.objects.create(
            name='Neg rate flat', algorithm=ServiceItem.FLAT_FEE,
            rate=Decimal('-5.00'), unit_label='each', accounting_category=self.ac,
        )
        output = self._run()
        self.assertIn('flat-fee', output.lower())

    def test_valid_flat_fee_not_flagged(self):
        self._make_sp(name='Good flat', rate=Decimal('50.00'))
        output = self._run()
        self.assertNotIn('flat-fee', output.lower())

    # ── active_modifiers dict-shape checks ───────────────────────

    def test_flags_dict_active_modifiers_on_task(self):
        sp = self._make_sp(name='Sp-task')
        job = self._make_job('J-VDT-002')
        # Bypass full_clean to force a dict into the JSONField
        Task.objects.filter(pk=Task.objects.create(
            name='Bad task', job=job, service_item=sp,
            active_modifiers=[],
        ).pk).update(active_modifiers={'key': 'val'})
        output = self._run()
        self.assertIn('active_modifiers', output.lower())

    def test_flags_dict_active_modifiers_on_plan_task(self):
        sp = self._make_sp(name='Sp-pt')
        job = self._make_job('J-VDT-003')
        ws = EstWorksheet.objects.create(job=job)
        PlanTask.objects.filter(pk=PlanTask.objects.create(
            name='Bad plan task', est_worksheet=ws, service_item=sp,
            active_modifiers=[], est_qty=Decimal('1.00'),
        ).pk).update(active_modifiers={'key': 'val'})
        output = self._run()
        self.assertIn('active_modifiers', output.lower())

    def test_flags_dict_default_active_modifiers_on_task_template(self):
        from apps.estimates.models import TaskTemplate
        sp = self._make_sp(name='Sp-tt')
        tt = TaskTemplate.objects.create(
            template_name='Bad Template',
            service_item=sp,
            default_active_modifiers=[],
            default_billable_qty=Decimal('1.00'),
        )
        TaskTemplate.objects.filter(pk=tt.pk).update(default_active_modifiers={'key': 'val'})
        output = self._run()
        self.assertIn('default_active_modifiers', output.lower())

    # ── Negative rate / percentage checks ───────────────────────

    def test_negative_rate_only_allowed_for_percentage(self):
        """A percentage ServiceItem with a negative rate (discount) is OK."""
        ServiceItem.objects.create(
            name='disc', algorithm=ServiceItem.PERCENTAGE,
            rate=Decimal('-10'), unit_label='%', accounting_category=self.ac,
        )
        output = self._run()
        self.assertNotIn('disc', output)

    def test_negative_rate_non_percentage_is_flagged(self):
        """A non-percentage ServiceItem with a negative rate is an error."""
        ServiceItem.objects.create(
            name='bad-elapsed', algorithm=ServiceItem.ELAPSED_TIME,
            rate=Decimal('-5.00'), unit_label='hr', accounting_category=self.ac,
        )
        output = self._run()
        self.assertIn('bad-elapsed', output)
        self.assertIn('negative rate', output)

    def test_valid_list_active_modifiers_not_flagged(self):
        sp = self._make_sp(name='Sp-list')
        job = self._make_job('J-VDT-004')
        Task.objects.create(
            name='Good task', job=job, service_item=sp,
            active_modifiers=['mod1'],
        )
        output = self._run()
        self.assertNotIn('active_modifiers', output.lower())
