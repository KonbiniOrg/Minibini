"""Task 3.1: the estimate wizard's source pool projects the Job's Tasks +
Materials (job-owns-atoms refactor): work lives directly on the Job.

Also covers Task.compute_estimate_amount() (est_qty) vs Task.compute_amount()
(actuals): the estimate projection bills est_qty, the invoice projection bills
actuals.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItemSource
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material
from apps.jobs.models import Job, Task, RateScheme


class EstimateSourcesFromJobTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        # Two Tasks directly on the Job (the new model: Job owns atoms).
        self.task_a = Task.objects.create(
            job=self.job, name='Setup', rate_scheme=self.scheme, est_qty=Decimal('2'),
        )
        self.task_b = Task.objects.create(
            job=self.job, name='Teardown', rate_scheme=self.scheme, est_qty=Decimal('3'),
        )
        # One Material directly on the Job (task-less).
        self.material = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('4'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def test_pool_returns_job_tasks_and_material(self):
        pool = EstimateWizardService.get_source_pool(self.estimate)
        by_key = {(a['type'], a['id']): a for a in pool['atoms']}
        self.assertEqual(len(pool['atoms']), 3)
        self.assertIn(('task', self.task_a.pk), by_key)
        self.assertIn(('task', self.task_b.pk), by_key)
        self.assertIn(('material', self.material.pk), by_key)
        for atom in pool['atoms']:
            self.assertIn(atom['type'], {'task', 'material'})
            self.assertEqual(atom['state'], 'available')

    def test_pool_amounts_use_est_qty(self):
        pool = EstimateWizardService.get_source_pool(self.estimate)
        amounts = {(a['type'], a['id']): a['amount'] for a in pool['atoms']}
        # ELAPSED_TIME with no bleps: actuals would be 0, but the estimate uses est_qty.
        self.assertEqual(amounts[('task', self.task_a.pk)], Decimal('200.00'))
        self.assertEqual(amounts[('task', self.task_b.pk)], Decimal('300.00'))
        self.assertEqual(amounts[('material', self.material.pk)], Decimal('20.00'))

    def test_projecting_writes_task_and_material_source_rows(self):
        line_item = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [
                {'type': 'task', 'id': self.task_a.pk},
                {'type': 'material', 'id': self.material.pk},
            ],
        )
        source_types = set(
            EstimateLineItemSource.objects
            .filter(estimate_line_item=line_item)
            .values_list('source_type', flat=True)
        )
        self.assertEqual(
            source_types,
            {EstimateLineItemSource.SOURCE_TASK, EstimateLineItemSource.SOURCE_MATERIAL},
        )

    def test_claimed_atom_state_reflects_current_estimate(self):
        EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': self.task_a.pk}],
        )
        pool = EstimateWizardService.get_source_pool(self.estimate)
        states = {(a['type'], a['id']): a['state'] for a in pool['atoms']}
        self.assertEqual(states[('task', self.task_a.pk)], 'claimed_by_current')
        self.assertEqual(states[('task', self.task_b.pk)], 'available')
        self.assertEqual(states[('material', self.material.pk)], 'available')


class TaskComputeEstimateAmountTest(TestCase):
    """compute_estimate_amount() bills est_qty; compute_amount() bills actuals."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-1',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        # ENTERED_QTY: actuals come from actual_qty, estimate from est_qty.
        self.scheme = RateScheme.objects.create(
            name='Per-unit', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('100'), unit_label='unit', accounting_category=self.cat,
        )
        self.task = Task.objects.create(
            job=self.job, name='Machining', rate_scheme=self.scheme,
            est_qty=Decimal('2'), actual_qty=Decimal('5'),
        )

    def test_estimate_amount_uses_est_qty(self):
        self.assertEqual(self.task.compute_estimate_amount(), Decimal('200.00'))

    def test_compute_amount_uses_actuals(self):
        self.assertEqual(self.task.compute_amount(), Decimal('500.00'))

    def test_estimate_and_actual_amounts_differ(self):
        self.assertNotEqual(
            self.task.compute_estimate_amount(), self.task.compute_amount(),
        )
