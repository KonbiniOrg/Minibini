"""Bundling 2+ atoms in a wizard: when every atom is a task sharing
identical (rate, unit_label, active_modifiers), the line item is
summarized (units = the tasks' own unit_label, qty = summed actuals,
price = the common effective rate) instead of the qty=1 / units='none'
fallback.

Task-owned money (Phase 1): uniformity is judged on the tasks' own money
fields, NOT on source_scheme provenance. Two tasks stamped from different
RateScheme presets (or one stamped, one hand-edited/never stamped) still
bundle uniformly if their current rate/unit_label/active_modifiers agree.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material, InventoryItem
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Blep, Job, RateScheme, Task


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
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 50}],
            accounting_category=self.cat,
        )
        self.scheme_other = RateScheme.objects.create(
            name='Jobs', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('99.00'), unit_label='jobs',
            accounting_category=self.cat,
        )

    def _task(self, scheme, actual_qty, modifiers=None):
        # Stamp copies the preset's money fields onto the task at creation
        # time (task-owned-money Phase 1); the task's own fields, not the
        # scheme, drive the wizard from here on.
        t = Task(job=self.job, name='T')
        t.stamp_from_scheme(scheme, modifier_keys=modifiers or [])
        t.actual_qty = Decimal(str(actual_qty))
        t.save()
        # Complete the task so it is billable (Task 5: only complete tasks are billable).
        t.status = Task.STATUS_COMPLETE
        t.save()
        return t

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

    def test_same_money_different_scheme_still_summarized(self):
        # Two tasks with identical (rate, unit_label, active_modifiers) but
        # stamped from DIFFERENT scheme presets still bundle uniformly —
        # uniformity is judged on task money, never on source_scheme.
        other_same_money = RateScheme.objects.create(
            name='Widgets-2', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='widgets',
            accounting_category=self.cat,
        )
        a = self._task(self.scheme, 3)
        b = self._task(other_same_money, 2)
        self.assertNotEqual(a.source_scheme_id, b.source_scheme_id)
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'widgets')
        self.assertEqual(li.qty, Decimal('5'))
        self.assertEqual(li.price, Decimal('10.00'))

    def test_elapsed_time_same_scheme_sums_blep_hours(self):
        # elapsed_time bills logged time: the bundle sums each task's Blep
        # hours (the actuals), never est_qty. These tasks carry no est_qty,
        # so a non-zero summed qty can only come from the Bleps.
        scheme_hourly = RateScheme.objects.create(
            name='Bench', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        a = Task(job=self.job, name='T')
        a.stamp_from_scheme(scheme_hourly)
        a.save()
        b = Task(job=self.job, name='T')
        b.stamp_from_scheme(scheme_hourly)
        b.save()
        start = timezone.now()
        Blep.objects.create(task=a, user=self.user, start_time=start, end_time=start + timedelta(hours=2))
        Blep.objects.create(task=b, user=self.user, start_time=start, end_time=start + timedelta(hours=3))
        # Complete tasks so they are billable (Task 5: only complete tasks are billable).
        a.status = Task.STATUS_COMPLETE
        a.save()
        b.status = Task.STATUS_COMPLETE
        b.save()
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'hour')
        self.assertEqual(li.qty, Decimal('5.00'))  # 2h + 3h from Bleps, not 1
        self.assertEqual(li.price, Decimal('50.00'))

    def test_different_money_fall_back(self):
        a = self._task(self.scheme, 3)        # 3 * 10 = 30
        b = self._task(self.scheme_other, 1)  # 1 * 99 = 99
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.price, Decimal('129.00'))

    def test_same_rate_different_modifiers_fall_back(self):
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
        # Consume the material so it is billable (Task 5: only consumed materials are billable).
        mat.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        mat.save(update_fields=['consumption_state'])
        atoms = [{'type': 'task', 'id': a.pk}, {'type': 'material', 'id': mat.pk}]
        li = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))

    def test_single_entered_qty_task_keeps_qty_and_rate(self):
        # A single ENTERED_QTY task carries its real qty × rate onto the
        # line (matching what a uniform multi-task bundle already did),
        # instead of collapsing to qty 1 / price = total.
        a = self._task(self.scheme, 3)
        li = self._bundle(a)
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('10.00'))
        self.assertEqual(li.units, 'widgets')

    def test_add_material_makes_non_uniform_falls_back_to_reprice(self):
        # Adding a material to a task line item makes the source set
        # non-uniform: qty is kept and the per-unit price is recomputed.
        a = self._task(self.scheme, 3)  # 3 * 10 = 30
        li = self._bundle(a)            # single entered-qty task: qty=3, price=10
        mat = Material.objects.create(
            job=self.job, task=a, description='M',
            quantity=Decimal('1'), sell_price=Decimal('5.00'),
            accounting_category=self.cat_mat,
        )
        # Consume the material so it is billable (Task 5: only consumed materials are billable).
        mat.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        mat.save(update_fields=['consumption_state'])
        InvoiceWizardService.add_atoms_to_line_item(
            li, [{'type': 'material', 'id': mat.pk}],
        )
        li.refresh_from_db()
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('11.67'))  # round(35 / 3, 2)


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
        self.scheme = RateScheme.objects.create(
            name='E-Widgets', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='widgets',
            accounting_category=self.cat,
        )
        self.scheme_rush = RateScheme.objects.create(
            name='E-Widgets-rush', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='widgets',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 50}],
            accounting_category=self.cat,
        )
        self.scheme_other = RateScheme.objects.create(
            name='E-Jobs', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('99.00'), unit_label='jobs',
            accounting_category=self.cat,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def _pt(self, scheme, est_qty, modifiers=None):
        # job-owns-atoms refactor (Task 3.1): estimate projects the Job's Tasks
        # (est_qty-based), now owned directly by the Job. Stamping (task-owned-
        # money Phase 1) copies the preset's money fields onto the task.
        t = Task(job=self.job, name='PT')
        t.stamp_from_scheme(scheme, modifier_keys=modifiers or [])
        t.est_qty = Decimal(str(est_qty))
        t.save()
        return t

    def _bundle(self, *pts):
        atoms = [{'type': 'task', 'id': p.pk} for p in pts]
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

    def test_same_money_different_scheme_still_summarized(self):
        # Uniformity is judged on task money, never on source_scheme —
        # two Tasks stamped from different presets with identical money
        # still bundle.
        other_same_money = RateScheme.objects.create(
            name='E-Widgets-2', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='widgets',
            accounting_category=self.cat,
        )
        a = self._pt(self.scheme, 3)
        b = self._pt(other_same_money, 2)
        self.assertNotEqual(a.source_scheme_id, b.source_scheme_id)
        li = self._bundle(a, b)
        self.assertEqual(li.units, 'widgets')
        self.assertEqual(li.qty, Decimal('5'))
        self.assertEqual(li.price, Decimal('10.00'))

    def test_flat_fee_same_scheme_summed(self):
        # flat_fee price now lives on RateScheme.rate; active_modifiers is [].
        # Same money (rate/unit_label/modifiers) summarizes — est_qty summed,
        # not set to 1.
        scheme_flat = RateScheme.objects.create(
            name='E-Tapping', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('7.00'), unit_label='holes',
            accounting_category=self.cat,
        )
        li = self._bundle(
            self._pt(scheme_flat, 4),
            self._pt(scheme_flat, 6),
        )
        self.assertEqual(li.units, 'holes')
        self.assertEqual(li.qty, Decimal('10'))  # 4 + 6 est_qty, not 1
        self.assertEqual(li.price, Decimal('7.00'))

    def test_different_money_fall_back(self):
        li = self._bundle(
            self._pt(self.scheme, 3), self._pt(self.scheme_other, 1),
        )
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))

    def test_same_rate_different_modifiers_fall_back(self):
        li = self._bundle(
            self._pt(self.scheme_rush, 2, ['rush']),
            self._pt(self.scheme_rush, 1, []),
        )
        self.assertEqual(li.units, 'none')
        self.assertEqual(li.qty, Decimal('1'))

    def test_bundle_with_material_falls_back(self):
        a = self._pt(self.scheme, 3)
        mat = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5'), accounting_category=self.cat_mat,
        )
        atoms = [
            {'type': 'task', 'id': a.pk},
            {'type': 'material', 'id': mat.pk},
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


class UniformMoneyBundleIgnoresProvenanceTest(TestCase):
    """The Task 6 brief's red test: bundle uniformity must be judged on the
    tasks' own money fields, not on source_scheme identity — two tasks with
    identical (rate, unit_label, active_modifiers) bundle uniformly even
    when one was never stamped from any preset (source_scheme=None) and the
    other was."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='UMB', name='UMB')
        contact = Contact.objects.create(
            first_name='U', last_name='M', email='u@m.com',
        )
        self.job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED, job_number='JOB-UMB',
        )
        self.scheme = RateScheme.objects.create(
            name='Bench-UMB', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('95.00'), unit_label='hour',
            accounting_category=self.cat,
        )

    def test_bundle_uniform_on_money_not_provenance(self):
        # t1: hand-set money fields, never stamped (source_scheme=None).
        t1 = Task(
            job=self.job, name='Hand-set', qty_source=Task.QTY_ENTERED,
            rate=Decimal('95.00'), unit_label='hour', active_modifiers=[],
            est_qty=Decimal('2.00'),
        )
        t1.save()
        # t2: stamped from a preset (source_scheme set), same money.
        t2 = Task(job=self.job, name='Stamped', est_qty=Decimal('3.00'))
        t2.stamp_from_scheme(self.scheme)
        t2.save()
        self.assertIsNone(t1.source_scheme_id)
        self.assertIsNotNone(t2.source_scheme_id)
        self.assertNotEqual(t1.source_scheme_id, t2.source_scheme_id)

        units, qty, price = EstimateWizardService._uniform_money_bundle([t1, t2])
        self.assertEqual((units, qty, price), ('hour', Decimal('5.00'), Decimal('95.00')))
