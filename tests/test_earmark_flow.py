"""
Tests for earmarking flow on job approval.
InventoryService earmark methods: get_earmark_preview() and create_earmarks_for_job().
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task
from apps.estimates.models import EstWorksheet
from apps.inventory.models import Material
from apps.inventory.models import PriceListItem
from apps.inventory.models import Earmark
from apps.inventory.services import InventoryService


class EarmarkPreviewTest(TestCase):
    """Tests for InventoryService.get_earmark_preview()."""

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
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, version=1,
        )

        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
        )
        self.screws = PriceListItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='box',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            is_inventoried=True,
        )

        self.task_a = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Build cabinets',
            description='Build cabinets',
            sort_order=1,
        )
        self.task_b = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Install trim',
            description='Install trim',
            sort_order=2,
        )

    def test_preview_aggregates_by_item(self):
        """Preview aggregates material quantities by price list item across tasks."""
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=self.task_b, price_list_item=self.plywood,
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]['price_list_item'], self.plywood)
        self.assertEqual(preview[0]['needed_qty'], Decimal('8.00'))

    def test_preview_shows_available_qty(self):
        """Preview shows current available quantity."""
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['available_qty'], Decimal('20.00'))

    def test_preview_shows_shortfall(self):
        """Preview shows shortfall when needed > available."""
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('25.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['shortfall'], Decimal('5.00'))

    def test_preview_no_shortfall_when_sufficient(self):
        """Preview shows zero shortfall when enough stock."""
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['shortfall'], Decimal('0.00'))

    def test_preview_multiple_items(self):
        """Preview handles multiple different items."""
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=self.task_a, price_list_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'), sell_price=Decimal('12.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 2)
        items = {p['price_list_item']: p for p in preview}
        self.assertEqual(items[self.plywood]['needed_qty'], Decimal('5.00'))
        self.assertEqual(items[self.screws]['needed_qty'], Decimal('2.00'))

    def test_preview_accounts_for_existing_earmarks(self):
        """Preview reduces available qty by existing earmarks from other jobs."""
        other_job = Job.objects.create(
            job_number='J-EMK-002', contact=self.contact, description='Other Job',
        )
        Earmark.objects.create(
            price_list_item=self.plywood, job=other_job, quantity=Decimal('15.00'),
        )
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('10.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        # 20 on hand - 15 earmarked = 5 available, need 10 → shortfall 5
        self.assertEqual(preview[0]['available_qty'], Decimal('5.00'))
        self.assertEqual(preview[0]['shortfall'], Decimal('5.00'))

    def test_preview_empty_when_no_inventoried_materials(self):
        """Preview returns empty list when no materials reference inventoried items."""
        Material.objects.create(
            task=self.task_a,
            description='Custom brackets',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'), sell_price=Decimal('20.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 0)

    def test_preview_ignores_non_inventoried_pli(self):
        """Preview ignores materials linked to non-inventoried price list items."""
        non_inv = PriceListItem.objects.create(
            code='NONINV', description='Not tracked', is_inventoried=False,
        )
        Material.objects.create(
            task=self.task_a, price_list_item=non_inv,
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'), sell_price=Decimal('20.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 0)


class CreateEarmarksForJobTest(TestCase):
    """Tests for InventoryService.create_earmarks_for_job()."""

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

        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
        )
        self.screws = PriceListItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='box',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            is_inventoried=True,
        )

    def test_creates_earmarks_from_data(self):
        """Creates earmarks from user-confirmed data."""
        earmark_data = [
            {'price_list_item_id': self.plywood.pk, 'quantity': Decimal('8.00')},
            {'price_list_item_id': self.screws.pk, 'quantity': Decimal('2.00')},
        ]
        InventoryService.create_earmarks_for_job(self.job, earmark_data)
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
        InventoryService.create_earmarks_for_job(self.job, earmark_data)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 1)
        earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('8.00'))

    def test_skips_zero_quantity(self):
        """Does not create earmarks for zero quantity."""
        earmark_data = [
            {'price_list_item_id': self.plywood.pk, 'quantity': Decimal('0.00')},
        ]
        InventoryService.create_earmarks_for_job(self.job, earmark_data)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)
