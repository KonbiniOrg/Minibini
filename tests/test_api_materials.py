from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, RateScheme
from apps.inventory.models import InventoryItem, Material
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
        self.pli = InventoryItem.objects.create(
            code='I-API', accounting_category=self.cat,
            qty_on_hand=Decimal('10'),
        )

    def test_post_jobs_id_materials_carries_units_freeform(self):
        """Issue 1 regression: freeform task-less Material POST must persist units."""
        url = f'/api/jobs/{self.job.pk}/materials/'
        resp = self.client.post(url, {
            'description': 'custom item',
            'quantity': '1',
            'units': 'lbs',
            'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        m = Material.objects.get(job=self.job, description='custom item')
        self.assertEqual(m.units, 'lbs')

    def test_post_jobs_id_materials_creates_taskless_material(self):
        url = f'/api/jobs/{self.job.pk}/materials/'
        resp = self.client.post(url, {
            'description': 'x', 'quantity': '3',
            'inventory_item': self.pli.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(Material.objects.filter(job=self.job, task__isnull=True).exists())

    def test_post_jobs_id_materials_customer_supplied(self):
        """Task 10: customer_supplied=True on the create API — born established
        at a locked $0, cost_source stamped, no purchase pricing accepted."""
        url = f'/api/jobs/{self.job.pk}/materials/'
        resp = self.client.post(url, {
            'description': 'customer panel', 'quantity': '2',
            'accounting_category': self.cat.pk,
            'customer_supplied': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        m = Material.objects.get(job=self.job, description='customer panel')
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.unit_cost, Decimal('0.00'))
        self.assertEqual(m.sell_price, Decimal('0.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_CUSTOMER)

    def test_post_customer_supplied_with_sell_price_400(self):
        """Reviewer gap: sell_price must be refused too — otherwise the pre-set
        sell rides establish()'s locked-sell preservation and mints a 99.00 lot."""
        url = f'/api/jobs/{self.job.pk}/materials/'
        resp = self.client.post(url, {
            'description': 'sneaky sell', 'quantity': '1',
            'accounting_category': self.cat.pk,
            'customer_supplied': True,
            'sell_price': '99.00',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)
        self.assertFalse(
            Material.objects.filter(job=self.job, description='sneaky sell').exists())

    def test_patch_pricing_on_customer_supplied_material_400(self):
        """A customer-supplied material's pricing is locked — PATCHing
        unit_cost/sell_price returns the standard 400 error-detail contract."""
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='theirs',
            quantity=Decimal('1'), accounting_category=self.cat, units='ea',
            customer_supplied=True,
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/', {'unit_cost': '5.00'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_patch_pli_linked_material_rejects_field_edits(self):
        """PLI-linked Materials are immutable except for unit_cost/sell_price.
        PATCHing description (or any non-pricing field) returns 400. Quantity
        must be edited via /restock/ or /draw-more/."""
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        r1 = self.client.patch(f'/api/materials/{m.pk}/', {'description': 'y'}, format='json')
        self.assertEqual(r1.status_code, 400, r1.content)
        r2 = self.client.patch(f'/api/materials/{m.pk}/', {'quantity': '99'}, format='json')
        self.assertEqual(r2.status_code, 400, r2.content)

    def test_consume_restock_draw_more_actions(self):
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), inventory_item=self.pli,
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
            quantity=Decimal('1'), inventory_item=None,
            accounting_category=self.cat,
        )
        resp = self.client.delete(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.status_code, 405, resp.content)

    def test_draw_more_forbidden_on_expense_bound(self):
        from apps.inventory.services import MaterialService
        from apps.expenses.models import Expense
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), inventory_item=self.pli,
        )
        Expense.objects.create(
            entered_by=self.user, amount=Decimal('10'),
            purchased_on='2026-04-14', accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material=m,
        )
        r = self.client.post(f'/api/materials/{m.pk}/draw-more/', {'quantity': '1'}, format='json')
        self.assertEqual(r.status_code, 400)


class MaterialAssignTaskApiTest(APITestCase):
    """assign-task action: move a material to a different task (or make it taskless)."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c', code='MASGN1')
        self.scheme = RateScheme.objects.create(
            name='S-masgn', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.cat,
        )
        self.user = User.objects.create_user('masgn_u', password='p')
        self.client.force_login(self.user)
        contact = Contact.objects.create(first_name='C', last_name='T')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz; contact.save()
        self.job = Job.objects.create(job_number='JOB-ASGN-1', contact=contact)
        from apps.jobs.models import Task
        self.task_a = Task.objects.create(name='A', job=self.job, rate_scheme=self.scheme)
        self.task_b = Task.objects.create(name='B', job=self.job, rate_scheme=self.scheme)
        self.task_done = Task.objects.create(name='Done', job=self.job, status='complete', rate_scheme=self.scheme)
        self.other_job = Job.objects.create(job_number='JOB-ASGN-2', contact=contact)
        self.other_task = Task.objects.create(name='Other', job=self.other_job, rate_scheme=self.scheme)

    def _make(self, task=None):
        from apps.inventory.services import MaterialService
        return MaterialService.create_on_job(
            job=self.job, task=task, description='x',
            quantity=Decimal('1'), inventory_item=None,
            accounting_category=self.cat,
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
        from apps.inventory.services import MaterialService
        # Established + stocked so it can be consumed (consume() refuses
        # provisional): a nonzero unit_cost mints a lot, then bump its QOH.
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), unit_cost=Decimal('5'),
            accounting_category=self.cat,
        )
        m.inventory_item.qty_on_hand = m.quantity
        m.inventory_item.save()
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
        self.pli = InventoryItem.objects.create(
            code='I-PERM', accounting_category=self.cat,
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
            'accounting_category': self.cat.pk,
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


class MaterialInvoicedFreezeTest(APITestCase):
    """Task 4: sell_price and unconsume are blocked on an invoiced material."""

    def setUp(self):
        from apps.core.models import Configuration, AppState
        # NumberGenerationService needs these to auto-generate invoice_number.
        Configuration.objects.get_or_create(
            key='invoice_number_sequence',
            defaults={'value': 'INV-{year}-{counter:04d}'},
        )
        AppState.objects.get_or_create(key='invoice_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='c', code='MFRZ1')
        self.user = User.objects.create_user('mfrz_u', password='p')
        self.client.force_login(self.user)
        contact = Contact.objects.create(first_name='C', last_name='T')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='JOB-FRZ-1', contact=contact)
        self.pli = InventoryItem.objects.create(
            code='I-FRZ', accounting_category=self.cat,
            qty_on_hand=Decimal('10'),
        )

    def _make_consumed_material(self):
        """PLI-linked consumed material."""
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='pli mat',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        MaterialService.consume(m)
        return m

    def _make_freeform_material(self):
        """Provisional (no inventory_item) material. Stays pending — consume()
        now refuses provisional materials, and the sell-price freeze applies to
        any invoiced material regardless of consumption state, so this still
        exercises the freeform PATCH branch."""
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='freeform mat',
            quantity=Decimal('1'), inventory_item=None,
            accounting_category=self.cat,
        )
        return m

    def _invoice_material(self, material):
        """Create a draft Invoice with a line item sourced from material."""
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        inv = Invoice.objects.create(job=material.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='m', qty=material.quantity,
            units='none', price=material.sell_price,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )

    def test_update_pricing_blocks_sell_price_when_invoiced(self):
        from django.core.exceptions import ValidationError
        from apps.inventory.services import MaterialService
        mat = self._make_consumed_material()
        self._invoice_material(mat)
        with self.assertRaises(ValidationError):
            MaterialService.update_pricing(mat, sell_price=Decimal('99.00'))

    def test_unconsume_blocked_when_invoiced(self):
        from django.core.exceptions import ValidationError
        from apps.inventory.services import MaterialService
        mat = self._make_consumed_material()
        self._invoice_material(mat)
        with self.assertRaises(ValidationError):
            MaterialService.unconsume(mat)

    def test_patch_sell_price_blocked_on_invoiced_freeform_material(self):
        mat = self._make_freeform_material()
        self._invoice_material(mat)
        resp = self.client.patch(
            f'/api/materials/{mat.pk}/', {'sell_price': '77.00'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_sell_price_blocked_on_invoiced_pli_material(self):
        """API-level coverage for the PLI-linked branch in MaterialViewSet.partial_update.

        The view routes PLI-linked pricing PATCHes through MaterialService.update_pricing
        (apps/api/inventory/views.py ~135-148) and converts the resulting
        ValidationError to 400.  Without that guard, the PATCH would succeed (200)
        because the PLI branch skips the freeform sell_price check entirely.
        """
        mat = self._make_consumed_material()
        self._invoice_material(mat)
        resp = self.client.patch(
            f'/api/materials/{mat.pk}/', {'sell_price': '99.00'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
