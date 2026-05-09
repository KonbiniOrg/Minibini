"""
Tests for earmarking flow on job approval.
InventoryService earmark methods: get_earmark_preview() and create_earmarks_for_job().
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material, PriceListItem, Earmark
from apps.inventory.services import InventoryService


class EarmarkPreviewTest(TestCase):
    """Tests for InventoryService.get_earmark_preview() — queries Job-side Materials."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='J-EMK-001', contact=self.contact, description='Earmark Job',
        )

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )
        self.screws = PriceListItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='ea',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )

        self.scheme = RateScheme.objects.create(
            name='S-emk', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.category,
        )
        self.task_a = Task.objects.create(
            job=self.job,
            name='Build cabinets',
            sort_order=1,
            rate_scheme=self.scheme,
        )
        self.task_b = Task.objects.create(
            job=self.job,
            name='Install trim',
            sort_order=2,
            rate_scheme=self.scheme,
        )

    def test_preview_aggregates_by_item(self):
        """Preview aggregates material quantities by price list item across tasks."""
        Material.objects.create(
            job=self.job, task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            job=self.job, task=self.task_b, price_list_item=self.plywood,
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]['price_list_item'], self.plywood)
        self.assertEqual(preview[0]['needed_qty'], Decimal('8.00'))

    def test_preview_shows_available_qty(self):
        Material.objects.create(
            job=self.job, task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['available_qty'], Decimal('20.00'))

    def test_preview_shows_shortfall(self):
        Material.objects.create(
            job=self.job, task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('25.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['shortfall'], Decimal('5.00'))

    def test_preview_no_shortfall_when_sufficient(self):
        Material.objects.create(
            job=self.job, task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['shortfall'], Decimal('0.00'))

    def test_preview_multiple_items(self):
        Material.objects.create(
            job=self.job, task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            job=self.job, task=self.task_a, price_list_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'), sell_price=Decimal('12.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 2)
        items = {p['price_list_item']: p for p in preview}
        self.assertEqual(items[self.plywood]['needed_qty'], Decimal('5.00'))
        self.assertEqual(items[self.screws]['needed_qty'], Decimal('2.00'))

    def test_preview_accounts_for_existing_earmarks(self):
        other_job = Job.objects.create(
            job_number='J-EMK-002', contact=self.contact, description='Other Job',
        )
        Earmark.objects.create(
            price_list_item=self.plywood, job=other_job, quantity=Decimal('15.00'),
        )
        Material.objects.create(
            job=self.job, task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('10.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['available_qty'], Decimal('5.00'))
        self.assertEqual(preview[0]['shortfall'], Decimal('5.00'))

    def test_preview_empty_when_no_inventoried_materials(self):
        Material.objects.create(
            job=self.job, task=self.task_a,
            description='Custom brackets',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'), sell_price=Decimal('20.00'),
            accounting_category=self.category,
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 0)

    def test_preview_ignores_non_inventoried_pli(self):
        non_inv = PriceListItem.objects.create(
            code='NONINV', description='Not tracked', is_inventoried=False,
            accounting_category=self.category,
        )
        Material.objects.create(
            job=self.job, task=self.task_a, price_list_item=non_inv,
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'), sell_price=Decimal('20.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 0)


class UpsertEarmarksTest(TestCase):
    """Tests for InventoryService._upsert_earmarks() (internal upsert helper)."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='J-EMK-003', contact=self.contact, description='Earmark Job',
        )

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )
        self.screws = PriceListItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='ea',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )

    def test_creates_earmarks_from_data(self):
        """Creates earmarks from user-confirmed data."""
        earmark_data = [
            {'price_list_item_id': self.plywood.pk, 'quantity': Decimal('8.00')},
            {'price_list_item_id': self.screws.pk, 'quantity': Decimal('2.00')},
        ]
        InventoryService._upsert_earmarks(self.job, earmark_data)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 2)
        plywood_earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(plywood_earmark.quantity, Decimal('8.00'))

    def test_updates_existing_earmarks(self):
        """Updates quantity of existing earmarks rather than creating duplicates."""
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job, quantity=Decimal('3.00'),
        )
        earmark_data = [
            {'price_list_item_id': self.plywood.pk, 'quantity': Decimal('8.00')},
        ]
        InventoryService._upsert_earmarks(self.job, earmark_data)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 1)
        earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('8.00'))

    def test_skips_zero_quantity(self):
        """Does not create earmarks for zero quantity."""
        earmark_data = [
            {'price_list_item_id': self.plywood.pk, 'quantity': Decimal('0.00')},
        ]
        InventoryService._upsert_earmarks(self.job, earmark_data)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)


class CreateEarmarksForJobIsNoopTest(TestCase):
    def test_no_new_earmarks_when_materials_already_upserted(self):
        """After JobService.copy_from_worksheet populates a job, calling
        InventoryService.create_earmarks_for_job again should not change
        any earmark rows."""
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.jobs.models import Job, PlanTask, RateScheme
        from apps.estimates.models import EstWorksheet
        from apps.inventory.models import PriceListItem, PlanMaterial, Earmark
        from apps.inventory.services import InventoryService
        from apps.jobs.services import JobService
        # Setup - follow existing patterns in this file for Contact/Business/Job
        from apps.contacts.models import Contact, Business
        contact = Contact.objects.create(first_name='C', last_name='T')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz; contact.save()
        cat = AccountingCategory.objects.create(name='c', code='NOP1')
        scheme_ac = AccountingCategory.objects.create(name='nop-sc', code='NOP-SC')
        scheme = RateScheme.objects.create(
            name='S-nop', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=scheme_ac,
        )
        pli = PriceListItem.objects.create(
            code='I-NOP', accounting_category=cat, is_inventoried=True,
        )
        src_job = Job.objects.create(job_number='JOB-NOP-SRC', contact=contact)
        ws = EstWorksheet.objects.create(job=src_job)
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='pt',
            rate_scheme=scheme, est_qty=Decimal('1'),
        )
        PlanMaterial.objects.create(
            plan_task=pt, est_worksheet=ws,
            description='x', quantity=Decimal('3'), price_list_item=pli,
        )
        dst = Job.objects.create(job_number='JOB-NOP-DST', contact=contact)
        JobService.copy_from_worksheet(dst.pk, ws.pk)
        before = {(e.price_list_item_id, e.job_id): e.quantity for e in Earmark.objects.filter(job=dst)}
        InventoryService.create_earmarks_for_job(dst)
        after = {(e.price_list_item_id, e.job_id): e.quantity for e in Earmark.objects.filter(job=dst)}
        self.assertEqual(before, after)
