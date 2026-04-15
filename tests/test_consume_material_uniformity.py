"""Gap 4b: InventoryService.consume_material sets consumption_state=consumed."""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.inventory.models import Material, PriceListItem
from apps.inventory.services import InventoryService, MaterialService
from apps.jobs.models import Job, Task


class ConsumeMaterialUniformityTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='cu', code='CU1')
        self.contact = Contact.objects.create(
            first_name='Con', last_name='Sume',
            email='consume@test.com',
        )
        self.job = Job.objects.create(job_number='JOB-CU-1', contact=self.contact)
        self.task = Task.objects.create(job=self.job, name='t')
        self.pli = PriceListItem.objects.create(
            code='CU-I', accounting_category=self.cat,
            is_inventoried=True, qty_on_hand=Decimal('20'),
        )

    def test_consume_material_sets_state_consumed_on_task_attached(self):
        """InventoryService.consume_material must set consumption_state=consumed."""
        m = MaterialService.create_on_job(
            job=self.job, task=self.task, description='x',
            quantity=Decimal('3'), price_list_item=self.pli,
        )
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        InventoryService.consume_material(m)
        m.refresh_from_db()
        self.assertEqual(
            m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED,
            'consume_material must transition consumption_state to consumed',
        )
