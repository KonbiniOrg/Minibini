from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem,
)
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material
from apps.jobs.models import Job, RateScheme, Task


class PerUnitSplitServiceTest(TestCase):
    """Per-unit-lines spec Task 8: `add_atoms_to_new_line_item(...,
    per_unit=True, split_materials=True)` atomically mints TWO per-unit
    lines — a labor line claiming the task atoms and a materials line
    claiming the material atoms — instead of one bundled line.
    """

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB-SPLIT')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='j@example.com', mobile_number='555-0001',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('60'),
            unit_label='hour', accounting_category=self.cat,
        )

    def _task(self, est_qty):
        t = Task(job=self.job, name='Cut parts')
        t.stamp_from_scheme(self.scheme)
        t.est_qty = est_qty
        t.save()
        return t

    def _material(self, quantity, sell_price=Decimal('2.50')):
        return Material.objects.create(
            job=self.job, description='Oak', quantity=quantity,
            sell_price=sell_price, accounting_category=self.cat,
        )

    def test_split_materials_creates_two_per_unit_lines(self):
        task = self._task(Decimal('0.75'))
        material = self._material(Decimal('4'))
        atoms = [
            {'type': 'task', 'id': task.pk},
            {'type': 'material', 'id': material.pk},
        ]
        overrides = {
            'description': 'Dining chairs', 'qty': Decimal('10'),
            'units': 'each', 'price': Decimal('45.00'),  # task-only per-unit sum (0.75h * $60)
        }
        labor = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, atoms, overrides=overrides, per_unit=True, split_materials=True)

        materials = labor.materials_line_item
        self.assertIsNotNone(materials)
        self.assertNotEqual(labor.pk, materials.pk)

        # Labor line: task claim only, overrides drive description/qty/units/price.
        self.assertTrue(labor.per_unit)
        self.assertEqual(labor.description, 'Dining chairs')
        self.assertEqual(labor.qty, Decimal('10'))
        self.assertEqual(labor.units, 'each')
        self.assertEqual(labor.price, Decimal('45.00'))
        self.assertEqual(labor.sources.count(), 1)
        labor_src = labor.sources.get(source_type='task', source_pk=task.pk)
        self.assertEqual(labor_src.per_unit_qty, Decimal('0.75'))

        # Materials line: material claim only, description suffixed, same
        # qty/units, price = Σ material per-unit amounts (4 * $2.50 = $10.00).
        self.assertTrue(materials.per_unit)
        self.assertEqual(materials.description, 'Dining chairs — materials')
        self.assertEqual(materials.qty, Decimal('10'))
        self.assertEqual(materials.units, 'each')
        self.assertEqual(materials.price, Decimal('10.00'))
        self.assertEqual(materials.sources.count(), 1)
        materials_src = materials.sources.get(source_type='material', source_pk=material.pk)
        self.assertEqual(materials_src.per_unit_qty, Decimal('4.00'))

        # Atoms are each stamped to the whole-job total exactly once.
        task.refresh_from_db()
        material.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('7.50'))
        self.assertEqual(material.quantity, Decimal('40.00'))

    def test_split_materials_line_numbers_are_sequential(self):
        task = self._task(Decimal('1'))
        material = self._material(Decimal('2'))
        atoms = [
            {'type': 'task', 'id': task.pk},
            {'type': 'material', 'id': material.pk},
        ]
        overrides = {
            'description': 'Widgets', 'qty': Decimal('5'),
            'units': 'each', 'price': Decimal('60.00'),
        }
        labor = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, atoms, overrides=overrides, per_unit=True, split_materials=True)
        materials = labor.materials_line_item
        self.assertEqual(materials.line_number, labor.line_number + 1)

    def test_split_materials_requires_per_unit(self):
        task = self._task(Decimal('1'))
        material = self._material(Decimal('2'))
        atoms = [
            {'type': 'task', 'id': task.pk},
            {'type': 'material', 'id': material.pk},
        ]
        overrides = {
            'description': 'Widgets', 'qty': Decimal('5'),
            'units': 'each', 'price': Decimal('60.00'),
        }
        with self.assertRaises(Exception) as ctx:
            EstimateWizardService.add_atoms_to_new_line_item(
                self.estimate, atoms, overrides=overrides,
                per_unit=False, split_materials=True)
        self.assertIn(
            'Splitting materials onto their own line requires per-unit lines.',
            str(ctx.exception),
        )
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)

    def test_split_materials_requires_at_least_one_material(self):
        task = self._task(Decimal('1'))
        atoms = [{'type': 'task', 'id': task.pk}]
        overrides = {
            'description': 'Widgets', 'qty': Decimal('5'),
            'units': 'each', 'price': Decimal('60.00'),
        }
        with self.assertRaises(Exception) as ctx:
            EstimateWizardService.add_atoms_to_new_line_item(
                self.estimate, atoms, overrides=overrides,
                per_unit=True, split_materials=True)
        self.assertIn(
            'requires at least one task and one material', str(ctx.exception))
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)

    def test_split_materials_requires_at_least_one_task(self):
        material = self._material(Decimal('2'))
        atoms = [{'type': 'material', 'id': material.pk}]
        overrides = {
            'description': 'Widgets', 'qty': Decimal('5'),
            'units': 'each', 'price': Decimal('60.00'),
        }
        with self.assertRaises(Exception) as ctx:
            EstimateWizardService.add_atoms_to_new_line_item(
                self.estimate, atoms, overrides=overrides,
                per_unit=True, split_materials=True)
        self.assertIn(
            'requires at least one task and one material', str(ctx.exception))
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)


class PerUnitSplitAPITest(TestCase):
    """API-level: POST .../line-items-from-atoms/ with split_materials=true
    responds {'line_item', 'materials_line_item'}; the ordinary (non-split)
    response shape is unchanged (flat serializer.data)."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB-SPLIT-API')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.user = User.objects.create_user(username='split_u', password='p')
        self.user.user_permissions.add(Permission.objects.get(codename='can_manage_jobs'))
        self.client = APIClient()
        self.client.login(username='split_u', password='p')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-SPLIT-1')
        self.scheme = RateScheme.objects.create(
            name='Hourly-Split', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('60'), unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task(job=self.job, name='Cut parts', est_qty=Decimal('0.5'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        self.material = Material.objects.create(
            job=self.job, description='Oak', quantity=Decimal('3'),
            sell_price=Decimal('2.00'), accounting_category=self.cat,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def test_split_materials_response_shape(self):
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {
            'atoms': [
                {'type': 'task', 'id': self.task.pk},
                {'type': 'material', 'id': self.material.pk},
            ],
            'overrides': {
                'description': 'Chairs', 'qty': '4', 'units': 'each', 'price': '30.00',
            },
            'per_unit': True,
            'split_materials': True,
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIn('line_item', resp.data)
        self.assertIn('materials_line_item', resp.data)
        self.assertEqual(resp.data['line_item']['description'], 'Chairs')
        self.assertEqual(resp.data['materials_line_item']['description'], 'Chairs — materials')
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 2)

    def test_non_split_response_shape_unchanged(self):
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {'atoms': [{'type': 'task', 'id': self.task.pk}]}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        # Flat shape: line_item_id at the top level, no nested 'line_item' key.
        self.assertIn('line_item_id', resp.data)
        self.assertNotIn('materials_line_item', resp.data)


class ChangeOrderSiblingPerUnitLinesTest(TestCase):
    """Per-unit-lines spec §9 (reminder only, no enforcement): a replace-CO
    line targeting a per-unit line surfaces `sibling_per_unit_lines` —
    OTHER per-unit lines on the same estimate sharing the target's
    (pre-CO) qty."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='sib@example.com', mobile_number='555-0002',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-SIB-1')
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_ACCEPTED, estimate_number='EST-SIB-1', version=1)

        self.target = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Dining chairs',
            qty=Decimal('10'), price=Decimal('45.00'), per_unit=True,
        )
        self.sibling = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2,
            description='Materials for dining chairs',
            qty=Decimal('10'), price=Decimal('10.00'), per_unit=True,
        )
        # Different qty — must NOT show as a sibling.
        self.different_qty = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=3, description='Side tables',
            qty=Decimal('4'), price=Decimal('20.00'), per_unit=True,
        )
        # Not per-unit at all — must NOT show as a sibling, even at qty 10.
        self.non_per_unit = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=4, description='Hand line',
            qty=Decimal('10'), price=Decimal('5.00'), per_unit=False,
        )

        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.estimate)
        self.replace_line = ChangeOrderLineItem.objects.create(
            change_order=self.co, line_number=1, action=ChangeOrderLineItem.ACTION_REPLACE,
            description='Dining chairs (revised)', qty=Decimal('8'), price=Decimal('45.00'),
            target_line_item=self.target,
        )

    def test_sibling_list_excludes_target_and_non_matching_lines(self):
        from apps.estimates.agreement import compose_amended_agreement
        from apps.api.change_orders.serializers import serialize_amended_agreement

        result = serialize_amended_agreement(compose_amended_agreement(self.co))
        replaced_row = next(r for r in result['rows'] if r['kind'] == 'replaced')

        self.assertIn('sibling_per_unit_lines', replaced_row)
        siblings = replaced_row['sibling_per_unit_lines']
        descriptions = {s['description'] for s in siblings}
        self.assertEqual(descriptions, {'Materials for dining chairs'})
        sib = siblings[0]
        self.assertEqual(sib['estimate_line_id'], self.sibling.pk)
        self.assertEqual(Decimal(sib['qty']), Decimal('10'))

    def test_sibling_list_empty_when_no_other_per_unit_lines_share_qty(self):
        from apps.estimates.agreement import compose_amended_agreement
        from apps.api.change_orders.serializers import serialize_amended_agreement

        self.sibling.delete()
        result = serialize_amended_agreement(compose_amended_agreement(self.co))
        replaced_row = next(r for r in result['rows'] if r['kind'] == 'replaced')
        self.assertEqual(replaced_row['sibling_per_unit_lines'], [])

    def test_sibling_list_absent_or_empty_on_a_non_per_unit_target(self):
        # A replace line targeting a NON-per-unit line gets no reminder.
        plain_target = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=5, description='Plain line',
            qty=Decimal('10'), price=Decimal('5.00'), per_unit=False,
        )
        plain_replace = ChangeOrderLineItem.objects.create(
            change_order=self.co, line_number=2, action=ChangeOrderLineItem.ACTION_REPLACE,
            description='Plain line (revised)', qty=Decimal('10'), price=Decimal('6.00'),
            target_line_item=plain_target,
        )
        from apps.estimates.agreement import compose_amended_agreement
        from apps.api.change_orders.serializers import serialize_amended_agreement

        result = serialize_amended_agreement(compose_amended_agreement(self.co))
        row = next(
            r for r in result['rows']
            if r['kind'] == 'replaced' and r['co_line_id'] == plain_replace.pk
        )
        self.assertEqual(row['sibling_per_unit_lines'], [])
