"""
Tests for automatic earmarking when an estimate is accepted.
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task
from apps.estimates.models import Estimate, EstWorksheet
from apps.inventory.models import Material
from apps.inventory.models import PriceListItem
from apps.inventory.models import Earmark


class AutoEarmarkOnEstimateAcceptedTest(TestCase):
    """When an estimate is accepted, earmarks are auto-created for inventoried materials."""

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
            job_number='J-AEM-001', contact=self.contact, description='Auto Earmark Job',
        )

        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
        )
        self.screws = PriceListItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='ea',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            is_inventoried=True,
        )

        # Create estimate and worksheet with materials
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-AEM-001', version=1,
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, estimate=self.estimate, version=1,
        )
        self.task = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Build cabinets',
            description='Build cabinets',
            sort_order=1,
        )

    def test_earmarks_created_on_estimate_accepted(self):
        """Earmarks are auto-created when estimate transitions to accepted."""
        Material.objects.create(
            task=self.task, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=self.task, price_list_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'), sell_price=Decimal('12.00'),
        )

        # Transition estimate: draft → open → accepted
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 2)
        plywood_earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(plywood_earmark.quantity, Decimal('5.00'))
        screws_earmark = Earmark.objects.get(price_list_item=self.screws, job=self.job)
        self.assertEqual(screws_earmark.quantity, Decimal('2.00'))

    def test_aggregates_across_tasks(self):
        """Earmarks aggregate material quantities across multiple tasks."""
        task_b = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Install trim',
            description='Install trim',
            sort_order=2,
        )
        Material.objects.create(
            task=self.task, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=task_b, price_list_item=self.plywood,
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )

        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

        earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('8.00'))

    def test_no_earmarks_without_inventoried_materials(self):
        """No earmarks created when materials don't reference inventoried items."""
        Material.objects.create(
            task=self.task,
            description='Custom brackets',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'), sell_price=Decimal('20.00'),
        )

        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_no_earmarks_on_non_accepted_transitions(self):
        """Earmarks are NOT created for other status transitions."""
        Material.objects.create(
            task=self.task, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )

        # draft → open should not create earmarks
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_no_earmarks_when_no_materials(self):
        """No earmarks created when job has no materials at all."""
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)
