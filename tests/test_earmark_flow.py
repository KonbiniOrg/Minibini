"""
Tests for Phase 6: Earmarking flow on job approval.
EarmarkService: get_earmark_preview() and create_earmarks_for_job().
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, EstWorksheet, Task, Material
from apps.inventory.models import InventoryItem, Earmark
from apps.inventory.services import EarmarkService


class EarmarkPreviewTest(TestCase):
    """Tests for EarmarkService.get_earmark_preview()."""

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

        self.plywood = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
        )
        self.screws = InventoryItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='box',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
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

    def test_preview_aggregates_by_inventory_item(self):
        """Preview aggregates material quantities by inventory item across tasks."""
        Material.objects.create(
            task=self.task_a, inventory_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=self.task_b, inventory_item=self.plywood,
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = EarmarkService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]['inventory_item'], self.plywood)
        self.assertEqual(preview[0]['needed_qty'], Decimal('8.00'))

    def test_preview_shows_available_qty(self):
        """Preview shows current available quantity."""
        Material.objects.create(
            task=self.task_a, inventory_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = EarmarkService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['available_qty'], Decimal('20.00'))

    def test_preview_shows_shortfall(self):
        """Preview shows shortfall when needed > available."""
        Material.objects.create(
            task=self.task_a, inventory_item=self.plywood,
            quantity=Decimal('25.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = EarmarkService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['shortfall'], Decimal('5.00'))

    def test_preview_no_shortfall_when_sufficient(self):
        """Preview shows zero shortfall when enough stock."""
        Material.objects.create(
            task=self.task_a, inventory_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = EarmarkService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['shortfall'], Decimal('0.00'))

    def test_preview_multiple_items(self):
        """Preview handles multiple different inventory items."""
        Material.objects.create(
            task=self.task_a, inventory_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=self.task_a, inventory_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'), sell_price=Decimal('12.00'),
        )
        preview = EarmarkService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 2)
        items = {p['inventory_item']: p for p in preview}
        self.assertEqual(items[self.plywood]['needed_qty'], Decimal('5.00'))
        self.assertEqual(items[self.screws]['needed_qty'], Decimal('2.00'))

    def test_preview_accounts_for_existing_earmarks(self):
        """Preview reduces available qty by existing earmarks from other jobs."""
        other_job = Job.objects.create(
            job_number='J-EMK-002', contact=self.contact, description='Other Job',
        )
        Earmark.objects.create(
            inventory_item=self.plywood, job=other_job, quantity=Decimal('15.00'),
        )
        Material.objects.create(
            task=self.task_a, inventory_item=self.plywood,
            quantity=Decimal('10.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = EarmarkService.get_earmark_preview(self.job)
        # 20 on hand - 15 earmarked = 5 available, need 10 → shortfall 5
        self.assertEqual(preview[0]['available_qty'], Decimal('5.00'))
        self.assertEqual(preview[0]['shortfall'], Decimal('5.00'))

    def test_preview_empty_when_no_inventory_materials(self):
        """Preview returns empty list when no materials reference inventory items."""
        Material.objects.create(
            task=self.task_a,
            description='Custom brackets',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'), sell_price=Decimal('20.00'),
        )
        preview = EarmarkService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 0)


class CreateEarmarksForJobTest(TestCase):
    """Tests for EarmarkService.create_earmarks_for_job()."""

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

        self.plywood = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
        )
        self.screws = InventoryItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='box',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
        )

    def test_creates_earmarks_from_data(self):
        """Creates earmarks from user-confirmed data."""
        earmark_data = [
            {'inventory_item_id': self.plywood.pk, 'quantity': Decimal('8.00')},
            {'inventory_item_id': self.screws.pk, 'quantity': Decimal('2.00')},
        ]
        EarmarkService.create_earmarks_for_job(self.job, earmark_data)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 2)
        plywood_earmark = Earmark.objects.get(inventory_item=self.plywood, job=self.job)
        self.assertEqual(plywood_earmark.quantity, Decimal('8.00'))

    def test_updates_existing_earmarks(self):
        """Updates quantity of existing earmarks rather than creating duplicates."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job, quantity=Decimal('3.00'),
        )
        earmark_data = [
            {'inventory_item_id': self.plywood.pk, 'quantity': Decimal('8.00')},
        ]
        EarmarkService.create_earmarks_for_job(self.job, earmark_data)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 1)
        earmark = Earmark.objects.get(inventory_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('8.00'))

    def test_skips_zero_quantity(self):
        """Does not create earmarks for zero quantity."""
        earmark_data = [
            {'inventory_item_id': self.plywood.pk, 'quantity': Decimal('0.00')},
        ]
        EarmarkService.create_earmarks_for_job(self.job, earmark_data)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)
