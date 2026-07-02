from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material, Earmark, InventoryItem
from apps.inventory.services import MaterialService
from apps.core.models import AccountingCategory


class MaterialServiceCreateOnJobTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-MS-1', contact=self.contact,
                                      status=Job.STATUS_APPROVED)
        self.pli_inv = InventoryItem.objects.create(
            code='I', accounting_category=self.cat, is_catalog=True,
        )
        self.pli_noninv = InventoryItem.objects.create(
            code='N', accounting_category=self.cat, is_catalog=False,
        )
        self.scheme = RateScheme.objects.create(
            name='S-msc', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=self.cat,
        )

    def test_create_taskless_inventoried_upserts_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4.00'),
            inventory_item=self.pli_inv,
        )
        self.assertIsNone(m.task_id)
        self.assertEqual(m.job_id, self.job.pk)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        e = Earmark.objects.get(inventory_item=self.pli_inv, job=self.job)
        self.assertEqual(e.quantity, Decimal('4.00'))

    def test_create_taskless_lot_item_earmarks(self):
        """Universal tracking: a material backed by any item (catalog or lot)
        earmarks it. Only a None-item material skips earmarking."""
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4.00'),
            inventory_item=self.pli_noninv,
        )
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertTrue(Earmark.objects.filter(
            inventory_item=self.pli_noninv, job=self.job).exists())

    def test_create_task_attached_invariant_enforced(self):
        other = Job.objects.create(job_number='JOB-MS-2', contact=self.contact)
        t = Task.objects.create(job=other, name='t', rate_scheme=self.scheme)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            MaterialService.create_on_job(
                job=self.job, task=t,
                description='x', quantity=Decimal('1.00'),
            )

    def test_create_task_attached_inventoried_upserts_earmark(self):
        t = Task.objects.create(job=self.job, name='t', rate_scheme=self.scheme)
        m = MaterialService.create_on_job(
            job=self.job, task=t, description='x', quantity=Decimal('2.00'),
            inventory_item=self.pli_inv,
        )
        e = Earmark.objects.get(inventory_item=self.pli_inv, job=self.job)
        self.assertEqual(e.quantity, Decimal('2.00'))
        # Gap 4a: task-attached inventoried material must be CONSUMPTION_STATE_PENDING
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING,
                         'task-attached inventoried material should start as pending')
