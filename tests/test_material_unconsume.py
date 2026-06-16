"""Tests for MaterialService.unconsume — the inverse of consume.

Needed by the blep-cancel undo path (docs/plans/2026-05-24-blep-handling-changes.md
§2): cancelling an oops-blep that was the first activity on a task must un-consume
the task's materials so a later re-Start can consume them again.
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, Earmark, InventoryItem
from apps.inventory.services import MaterialService
from apps.core.models import AccountingCategory


class UnconsumeTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-U-1', contact=self.contact)
        self.pli = InventoryItem.objects.create(
            code='I', accounting_category=self.cat, is_catalog=True,
            qty_on_hand=Decimal('10'),
        )

    def test_unconsume_restores_qoh_sold_and_state(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('4'), inventory_item=self.pli,
        )
        MaterialService.consume(m)
        MaterialService.unconsume(m)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))
        self.assertEqual(self.pli.qty_sold, Decimal('0'))

    def test_unconsume_restores_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('4'), inventory_item=self.pli,
        )
        MaterialService.consume(m)
        self.assertFalse(
            Earmark.objects.filter(inventory_item=self.pli, job=self.job).exists()
        )
        MaterialService.unconsume(m)
        e = Earmark.objects.get(inventory_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('4'))

    def test_unconsume_requires_consumed_state(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        # still PENDING — unconsume must refuse
        with self.assertRaises(ValidationError):
            MaterialService.unconsume(m)

    def test_unconsume_no_item_just_flips_state(self):
        """A material with no inventory item flips state with no QOH effects
        (the only no-op path under universal tracking)."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), inventory_item=None,
            accounting_category=self.cat,
        )
        MaterialService.consume(m)
        MaterialService.unconsume(m)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_consume_unconsume_consume_round_trips(self):
        """After unconsume, the material is consumable again (the re-Start path)."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('4'), inventory_item=self.pli,
        )
        MaterialService.consume(m)
        MaterialService.unconsume(m)
        MaterialService.consume(m)  # must not raise
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        self.assertEqual(self.pli.qty_on_hand, Decimal('6'))
        self.assertEqual(self.pli.qty_sold, Decimal('4'))
