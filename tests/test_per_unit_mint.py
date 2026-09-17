"""Per-unit-lines spec §5/§6, Task 5: the mint flow (post-acceptance
checklist "Generate work..." gesture) for a plain accepted hand line.

The one-unit-or-whole-line question is asked ONCE per line — the first
claim can set `line.per_unit` (MintService.claim_atom_for_line's
`set_line_per_unit` param); later claims inherit it. On a per-unit line,
atoms are born with totals: the API view multiplies the submitted
per-unit `est_qty` / `quantity` / `est_worker_time` by `claim_line.qty`
before creating the atom, and passes the raw per-unit values to
`claim_atom_for_line` for the claim-row snapshot.

Object graph built by hand, mirroring tests/test_mint_service.py and
tests/test_mint_api.py.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.estimates.mint import MintService
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import Material
from apps.jobs.models import Job, RateScheme, Task


class MintServiceAskOncePerUnitTest(TestCase):
    """Service-level coverage of the ask-once rule and the per-unit-qty
    requirement — mirrors tests/test_mint_service.py's hand-built graph."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='PU1', name='Per Unit')
        contact = Contact.objects.create(
            first_name='P', last_name='U', email='pu@test.example', mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-PERUNIT-0001', status=Job.STATUS_APPROVED)
        self.scheme = RateScheme.objects.create(
            name='Per Unit Hourly', algorithm=RateScheme.ENTERED_QTY, rate=Decimal('100'),
            unit_label='ea', accounting_category=self.cat)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-PERUNIT-0001', status=Estimate.STATUS_DRAFT)
        self.line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='10 chairs',
            qty=Decimal('10'), price=Decimal('1500.00'), accounting_category=self.cat)
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_ACCEPTED)
        self.estimate.refresh_from_db()

    def _make_task(self, name='chair task', est_qty=Decimal('1')):
        task = Task(job=self.job, name=name, est_qty=est_qty)
        task.stamp_from_scheme(self.scheme)
        task.save()
        return task

    def test_first_mint_sets_line_per_unit(self):
        task = self._make_task()
        MintService.claim_atom_for_line(
            self.line, EstimateLineItemSource.SOURCE_TASK, task.pk,
            per_unit_qty=Decimal('0.75'), set_line_per_unit=True,
        )
        self.line.refresh_from_db()
        self.assertTrue(self.line.per_unit)

    def test_second_mint_cannot_flip_choice(self):
        task1 = self._make_task('first')
        MintService.claim_atom_for_line(
            self.line, EstimateLineItemSource.SOURCE_TASK, task1.pk,
            per_unit_qty=Decimal('0.75'), set_line_per_unit=True,
        )
        task2 = self._make_task('second')
        with self.assertRaises(ValidationError) as ctx:
            MintService.claim_atom_for_line(
                self.line, EstimateLineItemSource.SOURCE_TASK, task2.pk,
                per_unit_qty=Decimal('0.5'), set_line_per_unit=False,
            )
        self.assertIn('already set', str(ctx.exception))
        # Rolled back atomically — the second atom was never claimed, and
        # the line's interpretation is untouched.
        self.assertFalse(EstimateLineItemSource.objects.filter(
            source_type=EstimateLineItemSource.SOURCE_TASK, source_pk=task2.pk).exists())
        self.line.refresh_from_db()
        self.assertTrue(self.line.per_unit)

    def test_per_unit_mint_requires_per_unit_qty(self):
        task = self._make_task()
        with self.assertRaises(ValidationError) as ctx:
            MintService.claim_atom_for_line(
                self.line, EstimateLineItemSource.SOURCE_TASK, task.pk,
                set_line_per_unit=True,
            )
        self.assertIn('per-unit quantity is required', str(ctx.exception))
        self.assertFalse(EstimateLineItemSource.objects.filter(
            source_type=EstimateLineItemSource.SOURCE_TASK, source_pk=task.pk).exists())


class MintAPIPerUnitTest(TestCase):
    """API-level coverage of the multiply-before-create contract on the
    task-create and material-create mint endpoints."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='PU2', name='Per Unit API')
        self.scheme = RateScheme.objects.create(
            name='Per Unit API Scheme', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='ea', accounting_category=self.cat,
        )
        contact = Contact.objects.create(
            first_name='Per', last_name='Unit', email='per-unit-api@test.example')
        self.job = Job.objects.create(
            name='Per Unit Job', contact=contact, job_number='JOB-PERUNIT-API-001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-PERUNIT-API-001',
            status=Estimate.STATUS_DRAFT,
        )
        self.line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='10 chairs',
            qty=Decimal('10'), price=Decimal('1500.00'), accounting_category=self.cat,
        )
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_ACCEPTED)
        self.estimate.refresh_from_db()

        self.manager = User.objects.create_user(
            username='per_unit_mgr', password='testpass')
        self.manager.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.manager = User.objects.get(pk=self.manager.pk)

    def _tasks_url(self):
        return f'/api/jobs/{self.job.pk}/tasks/'

    def _materials_url(self):
        return f'/api/jobs/{self.job.pk}/materials/'

    def test_per_unit_mint_task_born_with_totals(self):
        self.client.force_login(self.manager)
        resp = self.client.post(self._tasks_url(), {
            'name': 'Assemble chair',
            'rate_scheme': self.scheme.pk,
            'est_qty': '0.75',
            'est_worker_time': '00:45:00',
            'claim_estimate_line': self.line.pk,
            'claim_line_per_unit': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        task = Task.objects.get(pk=resp.data['task_id'])
        self.assertEqual(task.est_qty, Decimal('7.50'))
        self.assertEqual(task.est_worker_time, timedelta(hours=7, minutes=30))

        self.line.refresh_from_db()
        self.assertTrue(self.line.per_unit)
        source = EstimateLineItemSource.objects.get(
            estimate_line_item=self.line,
            source_type=EstimateLineItemSource.SOURCE_TASK, source_pk=task.pk)
        self.assertEqual(source.per_unit_qty, Decimal('0.75'))
        self.assertEqual(source.per_unit_worker_time, timedelta(minutes=45))

    def test_per_unit_mint_material_born_with_totals(self):
        self.client.force_login(self.manager)
        resp = self.client.post(self._materials_url(), {
            'description': 'Chair leg bracket',
            'quantity': '4',
            'units': 'ea',
            'unit_cost': '2.00',
            'sell_price': '5.00',
            'accounting_category': self.cat.pk,
            'claim_estimate_line': self.line.pk,
            'claim_line_per_unit': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        material = Material.objects.get(pk=resp.data['material_id'])
        self.assertEqual(material.quantity, Decimal('40.00'))

        self.line.refresh_from_db()
        self.assertTrue(self.line.per_unit)
        source = EstimateLineItemSource.objects.get(
            estimate_line_item=self.line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL, source_pk=material.pk)
        self.assertEqual(source.per_unit_qty, Decimal('4.00'))
        self.assertIsNone(source.per_unit_worker_time)

    def test_whole_line_mint_unchanged(self):
        """Regression: a mint with no claim_line_per_unit on a line that
        has never been asked stays whole-line — no multiplication, no
        per-unit snapshot, per_unit stays False."""
        self.client.force_login(self.manager)
        resp = self.client.post(self._tasks_url(), {
            'name': 'Whole-line task',
            'rate_scheme': self.scheme.pk,
            'est_qty': '3',
            'claim_estimate_line': self.line.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        task = Task.objects.get(pk=resp.data['task_id'])
        self.assertEqual(task.est_qty, Decimal('3.00'))

        self.line.refresh_from_db()
        self.assertFalse(self.line.per_unit)
        source = EstimateLineItemSource.objects.get(
            estimate_line_item=self.line,
            source_type=EstimateLineItemSource.SOURCE_TASK, source_pk=task.pk)
        self.assertIsNone(source.per_unit_qty)
        self.assertIsNone(source.per_unit_worker_time)
