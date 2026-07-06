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
            code='I', accounting_category=self.cat,
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
        # Earmark restoration applies to committed (approved+) jobs — that's where
        # consume removed a real earmark. On an approved job create_on_job earmarks
        # at creation, consume removes it, and unconsume must put it back.
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
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

    def test_unconsume_preapproval_does_not_create_earmark(self):
        # self.job is DRAFT: consume made no earmark (pre-approval), so unconsume
        # must not create one either — QOH is still restored. Mirrors consume's
        # earmark no-op so draft jobs never carry earmarks (the D3 invariant).
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('4'), inventory_item=self.pli,
        )
        MaterialService.consume(m)
        MaterialService.unconsume(m)
        self.pli.refresh_from_db()
        self.assertFalse(
            Earmark.objects.filter(inventory_item=self.pli, job=self.job).exists()
        )
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))

    def test_unconsume_requires_consumed_state(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        # still PENDING — unconsume must refuse
        with self.assertRaises(ValidationError):
            MaterialService.unconsume(m)

    def test_unconsume_no_item_just_flips_state(self):
        """A consumed material with no inventory item flips back to pending with
        no QOH effects (unconsume's defensive no-item branch). consume() now
        refuses provisional materials, so this consumed-no-item state can only
        come from legacy data — construct it directly to exercise the branch."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), inventory_item=None,
            accounting_category=self.cat,
        )
        m.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        m.save(update_fields=['consumption_state'])
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
