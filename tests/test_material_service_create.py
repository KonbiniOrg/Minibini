from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material, Earmark, PriceListItem
from apps.inventory.services import MaterialService
from apps.core.models import AccountingCategory


class MaterialServiceCreateOnJobTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-MS-1', contact=self.contact)
        self.pli_inv = PriceListItem.objects.create(
            code='I', accounting_category=self.cat, is_inventoried=True,
        )
        self.pli_noninv = PriceListItem.objects.create(
            code='N', accounting_category=self.cat, is_inventoried=False,
        )
        self.scheme = RateScheme.objects.create(
            name='S-msc', algorithm=RateScheme.FLAT_FEE,
            rate=1, unit_label='ea', accounting_category=self.cat,
        )

    def test_create_taskless_inventoried_upserts_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4.00'),
            price_list_item=self.pli_inv,
        )
        self.assertIsNone(m.task_id)
        self.assertEqual(m.job_id, self.job.pk)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        e = Earmark.objects.get(price_list_item=self.pli_inv, job=self.job)
        self.assertEqual(e.quantity, Decimal('4.00'))

    def test_create_taskless_noninventoried_no_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4.00'),
            price_list_item=self.pli_noninv,
        )
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertFalse(Earmark.objects.exists())

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
            price_list_item=self.pli_inv,
        )
        e = Earmark.objects.get(price_list_item=self.pli_inv, job=self.job)
        self.assertEqual(e.quantity, Decimal('2.00'))
        # Gap 4a: task-attached inventoried material must be CONSUMPTION_STATE_PENDING
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING,
                         'task-attached inventoried material should start as pending')
