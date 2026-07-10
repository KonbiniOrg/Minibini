"""
qty_available on material serializers is earmark-aware (on_hand minus ALL
job earmarks), not just raw on_hand. Tests cover both the task-materials
endpoint (apps.api.tasks.serializers.MaterialSerializer) and the job
endpoint (apps.api.inventory.serializers.MaterialSerializer via JobSerializer).
"""
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.inventory.models import InventoryItem
from apps.inventory.services import MaterialService
from apps.jobs.models import Job, RateScheme, Task


def _setup_common():
    cat = AccountingCategory.objects.get_or_create(
        code='MAT_AVAIL', defaults={'name': 'Material Avail'},
    )[0]
    scheme = RateScheme.objects.get_or_create(
        name='Avail Test Scheme',
        defaults={
            'algorithm': RateScheme.ELAPSED_TIME,
            'rate': Decimal('10.00'),
            'unit_label': 'hour',
            'accounting_category': cat,
        },
    )[0]
    c = Contact.objects.create(first_name='A', last_name='B', work_number='0')
    item = InventoryItem.objects.create(
        code='AVAIL-ITEM', description='widget',
        accounting_category=cat,
        qty_on_hand=Decimal('10.00'),
    )
    return cat, c, item, scheme


class TaskMaterialQtyAvailableTest(TestCase):
    """GET /api/tasks/{id}/materials/ exposes earmark-aware qty_available."""

    def setUp(self):
        self.user = User.objects.create_user(username='u_tm', password='p')
        cat, c, self.item, scheme = _setup_common()

        self.job1 = Job.objects.create(job_number='J-AV1', contact=c, description='j1')
        self.job2 = Job.objects.create(job_number='J-AV2', contact=c, description='j2')

        # task for job1 — material to be tested
        self.task = Task.objects.create(job=self.job1, name='T', sort_order=0, rate_scheme=scheme)

        # job1 needs 6; job2 needs 7 — total earmarked 13, on_hand 10 → available -3
        MaterialService.create_on_job(
            job=self.job1, task=self.task,
            inventory_item=self.item,
            description='widget', quantity=Decimal('6.00'),
            units='none', unit_cost=Decimal('1.00'),
            sell_price=Decimal('2.00'), accounting_category=cat,
        )
        MaterialService.create_on_job(
            job=self.job2, task=None,
            inventory_item=self.item,
            description='widget', quantity=Decimal('7.00'),
            units='none', unit_cost=Decimal('1.00'),
            sell_price=Decimal('2.00'), accounting_category=cat,
        )

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_qty_available_is_earmark_aware(self):
        r = self.client.get(f'/api/tasks/{self.task.pk}/materials/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data), 1)
        self.assertIn('qty_available', data[0])
        self.assertEqual(data[0]['qty_available'], '-3.00')

    def test_qty_available_is_null_for_freeform_material(self):
        cat = AccountingCategory.objects.get(code='MAT_AVAIL')
        scheme = RateScheme.objects.get(name='Avail Test Scheme')
        task2 = Task.objects.create(job=self.job1, name='T2', sort_order=1, rate_scheme=scheme)
        MaterialService.create_on_job(
            job=self.job1, task=task2,
            inventory_item=None,
            description='freeform', quantity=Decimal('3.00'),
            units='none', unit_cost=Decimal('0.00'),
            sell_price=Decimal('0.00'), accounting_category=cat,
        )
        r = self.client.get(f'/api/tasks/{task2.pk}/materials/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data), 1)
        self.assertIsNone(data[0]['qty_available'])


class JobMaterialQtyAvailableTest(TestCase):
    """GET /api/jobs/{id}/ materials list exposes earmark-aware qty_available."""

    def setUp(self):
        self.user = User.objects.create_user(username='u_jm', password='p')
        cat, c, self.item, _scheme = _setup_common()

        self.job1 = Job.objects.create(job_number='J-JAV1', contact=c, description='j1')
        self.job2 = Job.objects.create(job_number='J-JAV2', contact=c, description='j2')

        # task-less materials on job1 (qty 4) and job2 (qty 8) → available = 10 - 12 = -2
        MaterialService.create_on_job(
            job=self.job1, task=None,
            inventory_item=self.item,
            description='widget', quantity=Decimal('4.00'),
            units='none', unit_cost=Decimal('1.00'),
            sell_price=Decimal('2.00'), accounting_category=cat,
        )
        MaterialService.create_on_job(
            job=self.job2, task=None,
            inventory_item=self.item,
            description='widget', quantity=Decimal('8.00'),
            units='none', unit_cost=Decimal('1.00'),
            sell_price=Decimal('2.00'), accounting_category=cat,
        )

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_qty_available_in_job_materials(self):
        r = self.client.get(f'/api/jobs/{self.job1.pk}/')
        self.assertEqual(r.status_code, 200)
        mats = r.json()['materials']
        self.assertEqual(len(mats), 1)
        self.assertIn('qty_available', mats[0])
        self.assertEqual(mats[0]['qty_available'], '-2.00')
