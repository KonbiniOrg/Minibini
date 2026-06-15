"""Tests for InventoryService QOH and earmark operations."""
from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.core.models import InventoryHistory
from apps.inventory.services import InventoryService, MaterialService
from apps.jobs.models import Job, Task, RateScheme
from apps.estimates.models import EstWorksheet, Estimate
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem


class ConsumeMaterialTest(TestCase):
    """Tests for MaterialService.consume."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User', email='test@test.com')
        self.job = Job.objects.create(
            job_number='JOB-001', contact=self.contact)

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.pli = InventoryItem.objects.create(
            code='PLI-001', description='Steel plate',
            is_catalog=True, qty_on_hand=Decimal('20.00'),
            qty_sold=Decimal('0.00'), accounting_category=self.category)
        self.scheme = RateScheme.objects.create(
            name='S-qohs1', algorithm=RateScheme.FLAT_FEE,
            rate=1, unit_label='ea', accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job, name='Cut steel',
            sort_order=1, rate_scheme=self.scheme)

    def test_decreases_qoh_and_increases_qty_sold(self):
        """Consuming material decreases QOH and increases qty_sold."""
        material = Material(
            job=self.job,
            task=self.task, price_list_item=self.pli,
            description='Steel plate', quantity=Decimal('5.00'),
            unit_cost=Decimal('50.00'))
        material.save()

        MaterialService.consume(material)

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('15.00'))
        self.assertEqual(self.pli.qty_sold, Decimal('5.00'))

    def test_reduces_earmark(self):
        """Consuming material reduces the earmark for the job."""
        Earmark.objects.create(
            price_list_item=self.pli, job=self.job,
            quantity=Decimal('10.00'))

        material = Material(
            job=self.job,
            task=self.task, price_list_item=self.pli,
            description='Steel plate', quantity=Decimal('3.00'),
            unit_cost=Decimal('50.00'))
        material.save()

        MaterialService.consume(material)

        earmark = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('7.00'))

    def test_deletes_earmark_when_fully_consumed(self):
        """Earmark is deleted when all earmarked quantity is consumed."""
        Earmark.objects.create(
            price_list_item=self.pli, job=self.job,
            quantity=Decimal('5.00'))

        material = Material(
            job=self.job,
            task=self.task, price_list_item=self.pli,
            description='Steel plate', quantity=Decimal('5.00'),
            unit_cost=Decimal('50.00'))
        material.save()

        MaterialService.consume(material)

        self.assertFalse(
            Earmark.objects.filter(price_list_item=self.pli, job=self.job).exists())

    def test_deletes_earmark_when_over_consumed(self):
        """Earmark is deleted when consumed quantity exceeds earmark."""
        Earmark.objects.create(
            price_list_item=self.pli, job=self.job,
            quantity=Decimal('3.00'))

        material = Material(
            job=self.job,
            task=self.task, price_list_item=self.pli,
            description='Steel plate', quantity=Decimal('5.00'),
            unit_cost=Decimal('50.00'))
        material.save()

        MaterialService.consume(material)

        self.assertFalse(
            Earmark.objects.filter(price_list_item=self.pli, job=self.job).exists())

    def test_no_earmark_no_error(self):
        """Consuming without an earmark does not raise."""
        material = Material(
            job=self.job,
            task=self.task, price_list_item=self.pli,
            description='Steel plate', quantity=Decimal('5.00'),
            unit_cost=Decimal('50.00'))
        material.save()

        MaterialService.consume(material)

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('15.00'))

    # (Removed test_skips_non_inventoried_items: under universal tracking a
    # non-catalog lot is NOT skipped — only a None-item material is, covered by
    # test_skips_no_pli below.)

    def test_skips_no_pli(self):
        """Materials without a PLI are silently skipped."""
        material = Material(
            job=self.job,
            task=self.task,
            description='Ad hoc material', quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            accounting_category=self.category)
        material.save()

        # Should not raise
        MaterialService.consume(material)

    def test_consume_via_job_task(self):
        """Consuming material on a job task reduces earmark for the task's job."""
        wo_task = Task.objects.create(
            job=self.job, name='Assemble', sort_order=1, rate_scheme=self.scheme)

        Earmark.objects.create(
            price_list_item=self.pli, job=self.job,
            quantity=Decimal('10.00'))

        material = Material(
            job=self.job,
            task=wo_task, price_list_item=self.pli,
            description='Steel plate', quantity=Decimal('4.00'),
            unit_cost=Decimal('50.00'))
        material.save()

        MaterialService.consume(material)

        earmark = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('6.00'))


class CompleteTaskAdjustmentTest(TestCase):
    """Tests for InventoryService.complete_task_adjustment."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User', email='test@test.com')
        self.job = Job.objects.create(
            job_number='JOB-001', contact=self.contact)

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.pli = InventoryItem.objects.create(
            code='PLI-001', description='Steel plate',
            is_catalog=True, qty_on_hand=Decimal('20.00'),
            qty_sold=Decimal('5.00'), accounting_category=self.category)
        self.scheme = RateScheme.objects.create(
            name='S-qohs2', algorithm=RateScheme.FLAT_FEE,
            rate=1, unit_label='ea', accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job, name='Cut steel',
            sort_order=1, rate_scheme=self.scheme)

        self.material = Material(
            job=self.job,
            task=self.task, price_list_item=self.pli,
            description='Steel plate', quantity=Decimal('5.00'),
            unit_cost=Decimal('50.00'))
        self.material.save()

    def test_no_change_when_actual_equals_estimated(self):
        """No adjustment when actual matches estimated."""
        InventoryService.complete_task_adjustment(
            self.material, Decimal('5.00'))

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('20.00'))
        self.assertEqual(self.pli.qty_sold, Decimal('5.00'))

    def test_over_consumption_decreases_qoh(self):
        """Actual > estimated: additional stock consumed."""
        InventoryService.complete_task_adjustment(
            self.material, Decimal('8.00'))

        self.pli.refresh_from_db()
        # difference = 8 - 5 = 3, so QOH decreases by 3, qty_sold increases by 3
        self.assertEqual(self.pli.qty_on_hand, Decimal('17.00'))
        self.assertEqual(self.pli.qty_sold, Decimal('8.00'))

    def test_under_consumption_returns_stock(self):
        """Actual < estimated: excess returned to stock."""
        InventoryService.complete_task_adjustment(
            self.material, Decimal('3.00'))

        self.pli.refresh_from_db()
        # difference = 3 - 5 = -2, so QOH increases by 2, qty_sold decreases by 2
        self.assertEqual(self.pli.qty_on_hand, Decimal('22.00'))
        self.assertEqual(self.pli.qty_sold, Decimal('3.00'))

    # (Removed test_skips_non_inventoried: under universal tracking
    # complete_task_adjustment runs for any item-backed material; the only
    # no-op path is a None-item material.)

    def test_skips_no_pli(self):
        """Materials without a PLI are silently skipped."""
        material = Material(
            job=self.job,
            task=self.task,
            description='Ad hoc', quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            accounting_category=self.category)
        material.save()

        # Should not raise
        InventoryService.complete_task_adjustment(material, Decimal('8.00'))


class ManualAdjustmentTest(TestCase):
    """Tests for InventoryService.manual_adjustment."""

    def setUp(self):
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.pli = InventoryItem.objects.create(
            code='PLI-001', description='Steel plate',
            is_catalog=True, qty_on_hand=Decimal('50.00'),
            qty_wasted=Decimal('0.00'), accounting_category=self.category)

    def test_positive_adjustment_increases_qoh(self):
        """Positive adjustment increases QOH."""
        InventoryService.manual_adjustment(
            self.pli, Decimal('10.00'), reason='Stock count correction')

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('60.00'))

    def test_positive_adjustment_does_not_affect_waste(self):
        """Positive adjustment does not change qty_wasted."""
        InventoryService.manual_adjustment(
            self.pli, Decimal('10.00'), reason='Found extra stock')

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_wasted, Decimal('0.00'))

    def test_negative_adjustment_decreases_qoh(self):
        """Negative adjustment decreases QOH."""
        InventoryService.manual_adjustment(
            self.pli, Decimal('-5.00'), reason='Damaged goods')

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('45.00'))

    def test_negative_adjustment_tracks_waste(self):
        """Negative adjustment increases qty_wasted."""
        InventoryService.manual_adjustment(
            self.pli, Decimal('-5.00'), reason='Damaged goods')

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_wasted, Decimal('5.00'))

    def _entries(self):
        return InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=self.pli.pk,
            entry_type='action')

    def test_creates_audit_record(self):
        """Adjustment records an InventoryHistory action entry."""
        InventoryService.manual_adjustment(
            self.pli, Decimal('-3.00'), reason='Spill damage')

        entry = self._entries().latest('timestamp')
        self.assertEqual(entry.changes['qty_change'], '-3.00')
        self.assertEqual(entry.text, 'Spill damage')

    def test_multiple_adjustments_create_multiple_records(self):
        """Each adjustment records its own audit entry."""
        InventoryService.manual_adjustment(
            self.pli, Decimal('10.00'), reason='Restock')
        InventoryService.manual_adjustment(
            self.pli, Decimal('-2.00'), reason='Breakage')

        self.assertEqual(self._entries().count(), 2)

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('58.00'))
        self.assertEqual(self.pli.qty_wasted, Decimal('2.00'))

    def test_zero_adjustment(self):
        """Zero adjustment still records an audit entry."""
        InventoryService.manual_adjustment(
            self.pli, Decimal('0.00'), reason='Verification')

        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('50.00'))
        self.assertEqual(self._entries().count(), 1)
