"""Bundling 2+ atoms in a wizard: when every atom is a task sharing one
RateScheme and identical active_modifiers, the line item is summarized
(units = scheme unit_label, qty = summed actuals, price = effective rate)
instead of the qty=1 / units='none' fallback."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import EstWorksheet
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material, PlanMaterial, InventoryItem
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Blep, Job, PlanTask, RateScheme, Task


class InvoiceWizardBundleSummaryTest(TestCase):
    def setUp(self):
        from apps.core.models import User
        self.user = User.objects.create_user(username='wizard_bundle_user')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.cat = AccountingCategory.objects.create(code='LBR', name='Labor')
        self.cat_mat = AccountingCategory.objects.create(code='MAT', name='Materials')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-1',
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        self.scheme = RateScheme.objects.create(
            name='Widgets', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='widgets',
            accounting_category=self.cat,
        )
        self.scheme_rush = RateScheme.objects.create(
            name='Widgets-rush', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='widgets',
            modifiers=[{'key': 'rush', 'percent': 50}],
            accounting_category=self.cat,
        )
        self.scheme_other = RateScheme.objects.create(
            name='Jobs', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('99.00'), unit_label='jobs',
            accounting_category=self.cat,
        )

    def _task(self, scheme, actual_qty, modifiers=None):
        return Task.objects.create(
            job=self.job, name='T', rate_scheme=scheme,
            actual_qty=Decimal(str(actual_qty)),
            active_modifiers=modifiers or [],
        )

    def _bundle(self, *tasks):
        atoms = [{'type': 'task', 'id': t.pk} for t in tasks]
        return InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)

    def test_same_scheme_no_modifiers_summarized(self):
        a = self._task(self.scheme, 3)
        b = self._task(self.scheme, 2)
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'widgets')
        self.assertEqual(li.qty, Decimal('5'))
        self.assertEqual(li.price, Decimal('10.00'))

    def test_same_scheme_identical_modifiers_uses_effective_rate(self):
        a = self._task(self.scheme_rush, 2, ['rush'])
        b = self._task(self.scheme_rush, 4, ['rush'])
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'widgets')
        self.assertEqual(li.qty, Decimal('6'))
        self.assertEqual(li.price, Decimal('15.00'))  # 10.00 * 1.5

    def test_elapsed_time_same_scheme_sums_blep_hours(self):
        # elapsed_time bills logged time: the bundle sums each task's Blep
        # hours (the actuals), never est_qty. These tasks carry no est_qty,
        # so a non-zero summed qty can only come from the Bleps.
        scheme_hourly = RateScheme.objects.create(
            name='Bench', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hours',
            accounting_category=self.cat,
        )
        a = Task.objects.create(job=self.job, name='T', rate_scheme=scheme_hourly)
        b = Task.objects.create(job=self.job, name='T', rate_scheme=scheme_hourly)
        start = timezone.now()
        Blep.objects.create(task=a, user=self.user, start_time=start, end_time=start + timedelta(hours=2))
        Blep.objects.create(task=b, user=self.user, start_time=start, end_time=start + timedelta(hours=3))
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'hours')
        self.assertEqual(li.qty, Decimal('5.00'))  # 2h + 3h from Bleps, not 1
        self.assertEqual(li.price, Decimal('50.00'))

    def test_different_schemes_fall_back(self):
        a = self._task(self.scheme, 3)        # 3 * 10 = 30
        b = self._task(self.scheme_other, 1)  # 1 * 99 = 99
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.price, Decimal('129.00'))

    def test_same_scheme_different_modifiers_fall_back(self):
        a = self._task(self.scheme_rush, 2, ['rush'])  # 2 * 15 = 30
        b = self._task(self.scheme_rush, 1, [])        # 1 * 10 = 10
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.price, Decimal('40.00'))

    def test_bundle_with_material_falls_back(self):
        a = self._task(self.scheme, 3)
        mat = Material.objects.create(
            job=self.job, task=a, description='Plywood',
            quantity=Decimal('1.00'), sell_price=Decimal('5.00'),
            accounting_category=self.cat_mat,
        )
        atoms = [{'type': 'task', 'id': a.pk}, {'type': 'material', 'id': mat.pk}]
        li = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))

    def test_single_task_unchanged(self):
        a = self._task(self.scheme, 3)
        li = self._bundle(a)
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.price, Decimal('30.00'))
        self.assertEqual(li.units, 'widgets')

    def test_add_material_makes_non_uniform_falls_back_to_reprice(self):
        # Adding a material to a task line item makes the source set
        # non-uniform: qty is kept and the per-unit price is recomputed.
        a = self._task(self.scheme, 3)  # 3 * 10 = 30
        li = self._bundle(a)            # single task: qty=1, price=30
        mat = Material.objects.create(
            job=self.job, task=a, description='M',
            quantity=Decimal('1'), sell_price=Decimal('5.00'),
            accounting_category=self.cat_mat,
        )
        InvoiceWizardService.add_atoms_to_line_item(
            li, [{'type': 'material', 'id': mat.pk}],
        )
        li.refresh_from_db()
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.price, Decimal('35.00'))


class EstimateWizardBundleSummaryTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        self.cat = AccountingCategory.objects.create(code='ELBR', name='Labor')
        self.cat_mat = AccountingCategory.objects.create(code='EMAT', name='Materials')
        self.contact = Contact.objects.create(
            first_name='E', last_name='D', email='e@d.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-E1',
        )
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='E-Widgets', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='widgets',
            accounting_category=self.cat,
        )
        self.scheme_rush = RateScheme.objects.create(
            name='E-Widgets-rush', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='widgets',
            modifiers=[{'key': 'rush', 'percent': 50}],
            accounting_category=self.cat,
        )
        self.scheme_other = RateScheme.objects.create(
            name='E-Jobs', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('99.00'), unit_label='jobs',
            accounting_category=self.cat,
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def _pt(self, scheme, est_qty, modifiers=None):
        return PlanTask.objects.create(
            est_worksheet=self.ws, name='PT', rate_scheme=scheme,
            est_qty=Decimal(str(est_qty)), active_modifiers=modifiers or [],
        )

    def _bundle(self, *pts):
        atoms = [{'type': 'plan_task', 'id': p.pk} for p in pts]
        return EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)

    def test_same_scheme_no_modifiers_summarized(self):
        li = self._bundle(self._pt(self.scheme, 3), self._pt(self.scheme, 2))
        self.assertEqual(li.units, 'widgets')
        self.assertEqual(li.qty, Decimal('5'))
        self.assertEqual(li.price, Decimal('10.00'))

    def test_same_scheme_identical_modifiers_uses_effective_rate(self):
        li = self._bundle(
            self._pt(self.scheme_rush, 2, ['rush']),
            self._pt(self.scheme_rush, 4, ['rush']),
        )
        self.assertEqual(li.units, 'widgets')
        self.assertEqual(li.qty, Decimal('6'))
        self.assertEqual(li.price, Decimal('15.00'))

    def test_flat_fee_same_scheme_summed(self):
        # flat_fee carries its unit price as a dict in active_modifiers; same
        # scheme + same price still summarizes — est_qty summed, not set to 1.
        scheme_flat = RateScheme.objects.create(
            name='E-Tapping', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('0.00'), unit_label='holes',
            accounting_category=self.cat,
        )
        li = self._bundle(
            self._pt(scheme_flat, 4, {'flat_fee_price': '7.00'}),
            self._pt(scheme_flat, 6, {'flat_fee_price': '7.00'}),
        )
        self.assertEqual(li.units, 'holes')
        self.assertEqual(li.qty, Decimal('10'))  # 4 + 6 est_qty, not 1
        self.assertEqual(li.price, Decimal('7.00'))

    def test_different_schemes_fall_back(self):
        li = self._bundle(
            self._pt(self.scheme, 3), self._pt(self.scheme_other, 1),
        )
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))

    def test_same_scheme_different_modifiers_fall_back(self):
        li = self._bundle(
            self._pt(self.scheme_rush, 2, ['rush']),
            self._pt(self.scheme_rush, 1, []),
        )
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))

    def test_bundle_with_plan_material_falls_back(self):
        a = self._pt(self.scheme, 3)
        pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5'), accounting_category=self.cat_mat,
        )
        atoms = [
            {'type': 'plan_task', 'id': a.pk},
            {'type': 'plan_material', 'id': pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))

    def test_remove_keeps_bundle_summarized(self):
        a = self._pt(self.scheme, 3)
        b = self._pt(self.scheme, 2)
        c = self._pt(self.scheme, 1)
        li = self._bundle(a, b, c)
        src = li.sources.filter(source_pk=a.pk).first()
        EstimateWizardService.remove_atoms_from_line_item(li, [src.source_id])
        li.refresh_from_db()
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('10.00'))
