from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem, Material
from apps.contacts.models import Contact, Business

User = get_user_model()


class MaterialApiTest(APITestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c', code='MAPI1')
        self.user = User.objects.create_user('mapi_u', password='p')
        self.client.force_login(self.user)
        # Create Contact/Business/Job per the patterns used elsewhere in the codebase.
        # Inspect tests/test_receive_po_uses_mutate_earmark.py or similar for the pattern.
        contact = Contact.objects.create(first_name='C', last_name='T')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz; contact.save()
        self.job = Job.objects.create(job_number='JOB-API-1', contact=contact)
        self.pli = PriceListItem.objects.create(
            code='I-API', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_post_jobs_id_materials_creates_taskless_material(self):
        url = f'/api/jobs/{self.job.pk}/materials/'
        resp = self.client.post(url, {
            'description': 'x', 'quantity': '3',
            'price_list_item': self.pli.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(Material.objects.filter(job=self.job, task__isnull=True).exists())

    def test_patch_material_description_only(self):
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        r1 = self.client.patch(f'/api/materials/{m.pk}/', {'description': 'y'}, format='json')
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = self.client.patch(f'/api/materials/{m.pk}/', {'quantity': '99'}, format='json')
        self.assertEqual(r2.status_code, 400)

    def test_consume_restock_draw_more_actions(self):
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), price_list_item=self.pli,
        )
        r = self.client.post(f'/api/materials/{m.pk}/draw-more/', {'quantity': '2'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.post(f'/api/materials/{m.pk}/restock/', {'quantity': '1'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.post(f'/api/materials/{m.pk}/consume/', format='json')
        self.assertEqual(r.status_code, 200, r.content)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)

    def test_draw_more_forbidden_on_expense_bound(self):
        from apps.inventory.services import MaterialService
        from apps.expenses.models import Expense
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), price_list_item=self.pli,
        )
        Expense.objects.create(
            entered_by=self.user, amount=Decimal('10'),
            purchased_on='2026-04-14', accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material=m,
        )
        r = self.client.post(f'/api/materials/{m.pk}/draw-more/', {'quantity': '1'}, format='json')
        self.assertEqual(r.status_code, 400)
