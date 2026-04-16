from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
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

    def test_delete_returns_405(self):
        """Gap 7: DELETE on /api/materials/{id}/ must return 405."""
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='del-me',
            quantity=Decimal('1'), price_list_item=None,
        )
        resp = self.client.delete(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.status_code, 405, resp.content)

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


class MaterialInventoriedFlagSerializerTest(APITestCase):
    """Task 7: `price_list_item_is_inventoried` should appear on serialized materials."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c', code='MIVF1')
        self.user = User.objects.create_user('mivf_u', password='p')
        self.client.force_login(self.user)
        contact = Contact.objects.create(first_name='C', last_name='T')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='JOB-MIVF-1', contact=contact)
        self.pli_inv = PriceListItem.objects.create(
            code='I-INV', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )
        self.pli_free = PriceListItem.objects.create(
            code='I-FREE', accounting_category=self.cat, is_inventoried=False,
        )

    def _make_material(self, pli):
        from apps.inventory.services import MaterialService
        return MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), price_list_item=pli,
        )

    def test_flag_true_for_inventoried_pli(self):
        m = self._make_material(self.pli_inv)
        resp = self.client.get(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('price_list_item_is_inventoried', resp.data)
        self.assertTrue(resp.data['price_list_item_is_inventoried'])

    def test_flag_false_for_non_inventoried_pli(self):
        m = self._make_material(self.pli_free)
        resp = self.client.get(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data['price_list_item_is_inventoried'])

    def test_flag_false_for_freeform_material(self):
        m = self._make_material(None)
        resp = self.client.get(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data['price_list_item_is_inventoried'])

    def test_flag_on_job_nested_materials(self):
        """The Job serializer's `materials` field should include the flag too."""
        m_inv = self._make_material(self.pli_inv)
        m_free = self._make_material(self.pli_free)
        m_none = self._make_material(None)
        resp = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        mats_by_id = {m['material_id']: m for m in resp.data['materials']}
        self.assertTrue(mats_by_id[m_inv.pk]['price_list_item_is_inventoried'])
        self.assertFalse(mats_by_id[m_free.pk]['price_list_item_is_inventoried'])
        self.assertFalse(mats_by_id[m_none.pk]['price_list_item_is_inventoried'])


class MaterialAssignTaskApiTest(APITestCase):
    """assign-task action: move a material to a different task (or make it taskless)."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c', code='MASGN1')
        self.user = User.objects.create_user('masgn_u', password='p')
        self.client.force_login(self.user)
        contact = Contact.objects.create(first_name='C', last_name='T')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz; contact.save()
        self.job = Job.objects.create(job_number='JOB-ASGN-1', contact=contact)
        from apps.jobs.models import Task
        self.task_a = Task.objects.create(name='A', job=self.job)
        self.task_b = Task.objects.create(name='B', job=self.job)
        self.task_done = Task.objects.create(name='Done', job=self.job, status='complete')
        self.other_job = Job.objects.create(job_number='JOB-ASGN-2', contact=contact)
        self.other_task = Task.objects.create(name='Other', job=self.other_job)

    def _make(self, task=None):
        from apps.inventory.services import MaterialService
        return MaterialService.create_on_job(
            job=self.job, task=task, description='x',
            quantity=Decimal('1'), price_list_item=None,
        )

    def test_assign_taskless_material_to_task(self):
        m = self._make(task=None)
        r = self.client.post(f'/api/materials/{m.pk}/assign-task/', {'task': self.task_a.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        m.refresh_from_db()
        self.assertEqual(m.task_id, self.task_a.pk)

    def test_move_material_between_tasks(self):
        m = self._make(task=self.task_a)
        r = self.client.post(f'/api/materials/{m.pk}/assign-task/', {'task': self.task_b.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        m.refresh_from_db()
        self.assertEqual(m.task_id, self.task_b.pk)

    def test_unassign_material_from_task(self):
        m = self._make(task=self.task_a)
        r = self.client.post(f'/api/materials/{m.pk}/assign-task/', {'task': None}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        m.refresh_from_db()
        self.assertIsNone(m.task_id)

    def test_reject_task_from_different_job(self):
        m = self._make(task=None)
        r = self.client.post(f'/api/materials/{m.pk}/assign-task/', {'task': self.other_task.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_reject_consumed_material(self):
        m = self._make(task=None)
        from apps.inventory.services import MaterialService
        MaterialService.consume(m)
        r = self.client.post(f'/api/materials/{m.pk}/assign-task/', {'task': self.task_a.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_reject_completed_task(self):
        m = self._make(task=None)
        r = self.client.post(f'/api/materials/{m.pk}/assign-task/', {'task': self.task_done.pk}, format='json')
        self.assertEqual(r.status_code, 400)


class MaterialApiPermissionTest(APITestCase):
    """Gap 8: Material endpoint uses IsAuthenticated only (not CanManageJobs)."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='perm', code='MAPERM1')
        contact = Contact.objects.create(first_name='P', last_name='T')
        biz = Business.objects.create(business_name='PBiz', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='JOB-PERM-1', contact=contact)
        self.pli = PriceListItem.objects.create(
            code='I-PERM', accounting_category=self.cat, is_inventoried=False,
        )

    def test_worker_with_no_atoms_can_create_material(self):
        """(a) Worker (zero permission atoms) can POST to /api/jobs/{id}/materials/."""
        worker = User.objects.create_user('perm_worker', password='p')
        # Ensure worker has no extra permissions
        worker.user_permissions.clear()
        self.client.force_login(worker)
        url = f'/api/jobs/{self.job.pk}/materials/'
        resp = self.client.post(url, {
            'description': 'worker item', 'quantity': '1',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_unauthenticated_client_is_rejected(self):
        """(b) Unauthenticated POST → 403 or 401."""
        # Do not log in — use a fresh client
        from rest_framework.test import APIClient
        anon_client = APIClient()
        url = f'/api/jobs/{self.job.pk}/materials/'
        resp = anon_client.post(url, {
            'description': 'anon item', 'quantity': '1',
        }, format='json')
        self.assertIn(resp.status_code, [401, 403],
                      f'Expected 401 or 403, got {resp.status_code}')
