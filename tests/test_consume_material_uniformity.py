"""Gap 4b: MaterialService.consume sets consumption_state=consumed."""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.inventory.models import Material, InventoryItem
from apps.inventory.services import MaterialService
from apps.jobs.models import Job, Task, RateScheme


class ConsumeMaterialUniformityTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='cu', code='CU1')
        self.scheme = RateScheme.objects.create(
            name='S-cu', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.cat,
        )
        self.contact = Contact.objects.create(
            first_name='Con', last_name='Sume',
            email='consume@test.com',
        )
        self.job = Job.objects.create(job_number='JOB-CU-1', contact=self.contact)
        self.task = Task.objects.create(job=self.job, name='t', rate_scheme=self.scheme)
        self.pli = InventoryItem.objects.create(
            code='CU-I', accounting_category=self.cat,
            is_catalog=True, qty_on_hand=Decimal('20'),
        )

    def test_consume_sets_state_consumed_on_task_attached(self):
        """MaterialService.consume must set consumption_state=consumed."""
        m = MaterialService.create_on_job(
            job=self.job, task=self.task, description='x',
            quantity=Decimal('3'), inventory_item=self.pli,
        )
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        MaterialService.consume(m)
        m.refresh_from_db()
        self.assertEqual(
            m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED,
            'consume must transition consumption_state to consumed',
        )
