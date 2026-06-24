from datetime import timedelta
from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.carry_over import AtomCarryOverService
from apps.estimates.models import Estimate, EstimateLineItem, EstWorksheet, TaskTemplate
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Earmark, Material, PlanMaterial, InventoryItem
from apps.jobs.models import Job, PlanTask, ServicePrice, Task


class CarryOverFromWorksheetAtomsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = ServicePrice.objects.create(
            name='Hourly', algorithm=ServicePrice.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup',
            service_price=self.scheme, est_qty=Decimal('2'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_creates_task_for_each_plan_task(self):
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 1)
        t = tasks.first()
        self.assertEqual(t.name, 'Setup')

    def test_carry_over_elapsed_time_sets_fields_on_task(self):
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        t = Task.objects.get(job=self.job)
        self.assertEqual(t.service_price, self.scheme)
        # elapsed_time scheme: actual_qty stays None (bleps will populate at invoice time)
        self.assertIsNone(t.actual_qty)
        self.assertEqual(t.est_qty, Decimal('2'))

    def test_carry_over_entered_qty_seeds_task_est_qty(self):
        # Replace scheme to entered_qty on the PlanTask
        scheme_qty = ServicePrice.objects.create(
            name='PerItem', algorithm=ServicePrice.ENTERED_QTY,
            rate=Decimal('50'), unit_label='item', accounting_category=self.cat,
        )
        self.pt.service_price = scheme_qty
        self.pt.est_qty = Decimal('2')
        self.pt.save()
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        t = Task.objects.get(job=self.job)
        self.assertEqual(t.est_qty, Decimal('2'))
        self.assertIsNone(t.actual_qty)

    def test_creates_material_for_each_plan_material(self):
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        materials = Material.objects.filter(job=self.job)
        self.assertEqual(materials.count(), 1)
        m = materials.first()
        self.assertEqual(m.description, 'steel')
        self.assertEqual(m.quantity, Decimal('3'))

    def test_idempotent_on_repeated_call(self):
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 1)

    def test_carry_over_preserves_sort_order_and_worker_time(self):
        self.pt.sort_order = 9
        self.pt.est_worker_time = timedelta(hours=4)
        self.pt.save()
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        t = Task.objects.get(job=self.job)
        self.assertEqual(t.sort_order, 9)
        self.assertEqual(t.est_worker_time, timedelta(hours=4))

    def test_carry_over_preserves_material_units(self):
        self.pm.units = 'kg'
        self.pm.save()
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        m = Material.objects.get(job=self.job)
        self.assertEqual(m.units, 'kg')

    def test_carry_over_creates_earmarks_for_inventoried_materials(self):
        pli = InventoryItem.objects.create(
            code='CO-EARM', accounting_category=self.cat, is_catalog=True,
            qty_on_hand=Decimal('50'),
        )
        PlanMaterial.objects.create(
            est_worksheet=self.ws, description='bar', quantity=Decimal('7'),
            units='ea', accounting_category=self.cat, inventory_item=pli,
        )
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        earmark = Earmark.objects.get(job=self.job, inventory_item=pli)
        self.assertEqual(earmark.quantity, Decimal('7'))


class CarryOverFromDirectLineItemsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0001',
        )
        self.scheme = ServicePrice.objects.create(
            name='Hourly', algorithm=ServicePrice.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.template = TaskTemplate.objects.create(
            template_name='Setup', service_price=self.scheme,
            default_billable_qty=Decimal('1.00'),
        )
        self.pli = InventoryItem.objects.create(
            code='STEEL', description='steel rod', units='ft',
            purchase_price=Decimal('3'), selling_price=Decimal('5'),
            accounting_category=self.cat,
        )

    def test_creates_task_from_template_ref(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('2'), units='hours',
            price=Decimal('100'), description='Setup',
            accounting_category=self.cat,
            source_template=self.template,
        )
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks.first().source_template, self.template)

    def test_creates_material_from_pli_ref(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('3'), units='ft',
            price=Decimal('5'), description='steel rod',
            accounting_category=self.cat,
            inventory_item=self.pli,
        )
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        materials = Material.objects.filter(job=self.job)
        self.assertEqual(materials.count(), 1)
        self.assertEqual(materials.first().inventory_item, self.pli)

    def test_skips_purely_manual_line_items(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('500'), description='one-off bespoke thing',
            accounting_category=self.cat,
        )
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 0)


class CarryOverUsesPlanTaskDirectlyTest(TestCase):
    """Verifies that AtomCarryOverService walks PlanTask atoms directly."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB2')
        self.contact = Contact.objects.create(
            first_name='A', last_name='B', email='a@b.com', mobile_number='555-1',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0002',
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.estimate = EstimateWizardService.open_for_worksheet(self.worksheet)

    def test_carry_over_uses_plan_task_directly(self):
        scheme = ServicePrice.objects.create(
            name='Carry Hourly', algorithm=ServicePrice.ENTERED_QTY,
            rate=Decimal('40.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        pt = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Inline atom',
            service_price=scheme, est_qty=Decimal('2.0'),
        )

        AtomCarryOverService.carry_over_for_estimate(self.estimate)

        task = Task.objects.get(source_plan_task=pt)
        self.assertEqual(task.service_price_id, scheme.pk)
        self.assertEqual(task.est_qty, Decimal('2.0'))

