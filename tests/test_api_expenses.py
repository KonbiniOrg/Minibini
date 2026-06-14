from decimal import Decimal
from datetime import date
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense

User = get_user_model()


def _seed_payment_accounts():
    Configuration.objects.update_or_create(
        key='qbo_payment_accounts',
        defaults={'value': (
            '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
        )},
    )


class ExpenseListScopingTest(TestCase):
    def setUp(self):
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

        self.worker_expense = Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('10.00'), purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        _seed_payment_accounts()
        self.admin_expense = Expense.objects.create(
            entered_by=self.admin,
            amount=Decimal('100.00'), purchased_on=date(2026, 4, 9),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
        )

    def test_unauthenticated_list_returns_403(self):
        r = self.client_http.get('/api/expenses/')
        self.assertIn(r.status_code, (401, 403))

    def test_worker_sees_only_own_purchased_expenses(self):
        self.client_http.force_login(self.worker)
        r = self.client_http.get('/api/expenses/')
        self.assertEqual(r.status_code, 200)
        ids = {row['id'] for row in r.json()['results']}
        self.assertEqual(ids, {self.worker_expense.pk})

    def test_admin_sees_all_expenses(self):
        self.client_http.force_login(self.admin)
        r = self.client_http.get('/api/expenses/')
        self.assertEqual(r.status_code, 200)
        ids = {row['id'] for row in r.json()['results']}
        self.assertEqual(ids, {self.worker_expense.pk, self.admin_expense.pk})


class ExpenseCreateTest(TestCase):
    def setUp(self):
        _seed_payment_accounts()
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        self.user = User.objects.create_user(username='u', password='testpass')
        self.client_http.force_login(self.user)

    def test_create_personal_returns_201(self):
        payload = {
            'amount': '47.50',
            'purchased_on': '2026-04-05',
            'accounting_category': self.cat.pk,
            'payment_method': 'personal',
            'purchased_by': self.user.pk,
        }
        r = self.client_http.post('/api/expenses/', payload, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Expense.objects.count(), 1)
        exp = Expense.objects.get()
        self.assertEqual(exp.status, Expense.STATUS_SUBMITTED)
        self.assertEqual(exp.entered_by, self.user)

    def test_create_personal_without_purchased_by_returns_400(self):
        payload = {
            'amount': '47.50',
            'purchased_on': '2026-04-05',
            'accounting_category': self.cat.pk,
            'payment_method': 'personal',
        }
        r = self.client_http.post('/api/expenses/', payload, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('purchased_by', r.json())

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
    def test_create_company_triggers_push(self, mock_push):
        mock_push.return_value = '9001'
        payload = {
            'amount': '218.45',
            'purchased_on': '2026-04-09',
            'accounting_category': self.cat.pk,
            'payment_method': 'company',
            'payment_account_id': '57',
        }
        r = self.client_http.post('/api/expenses/', payload, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        exp = Expense.objects.get()
        self.assertEqual(exp.status, Expense.STATUS_SYNCED)
        mock_push.assert_called_once()


class ExpenseCreateWithNewMaterialTest(TestCase):
    def setUp(self):
        from apps.contacts.models import Contact, Business
        from apps.jobs.models import Job
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'},
        )
        Configuration.objects.update_or_create(
            key='job_counter', defaults={'value': '0'},
        )
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        self.user = User.objects.create_user(username='u', password='testpass')
        self.client_http.force_login(self.user)
        self.contact = Contact.objects.create(
            first_name='A', last_name='B', email='a@b.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            job_number='JOB-2026-NM01', contact=self.contact,
        )

    def test_create_personal_with_new_material_job_id(self):
        payload = {
            'amount': '25.00',
            'purchased_on': '2026-04-05',
            'accounting_category': self.cat.pk,
            'payment_method': 'personal',
            'purchased_by': self.user.pk,
            'new_material': {
                'job_id': self.job.pk,
                'description': 'Bolts',
                'quantity': 5,
                'price': '25.00',
            },
        }
        r = self.client_http.post(
            '/api/expenses/', payload, content_type='application/json',
        )
        self.assertEqual(r.status_code, 201, r.content)
        exp = Expense.objects.get()
        self.assertIsNotNone(exp.material)
        self.assertEqual(exp.material.job_id, self.job.pk)
        self.assertIsNone(exp.material.task_id)

    def test_create_rejects_work_order_id_without_job_id(self):
        """Legacy work_order_id key no longer accepted."""
        payload = {
            'amount': '25.00',
            'purchased_on': '2026-04-05',
            'accounting_category': self.cat.pk,
            'payment_method': 'personal',
            'purchased_by': self.user.pk,
            'new_material': {
                'work_order_id': self.job.pk,
                'description': 'Bolts',
            },
        }
        r = self.client_http.post(
            '/api/expenses/', payload, content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)


class ExpenseRejectRetryTest(TestCase):
    def setUp(self):
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

    def test_reject_personal_expense_flips_status(self):
        exp = Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('10.00'), purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        self.client_http.force_login(self.admin)
        r = self.client_http.post(f'/api/expenses/{exp.pk}/reject/')
        self.assertEqual(r.status_code, 200, r.content)
        exp.refresh_from_db()
        self.assertEqual(exp.status, Expense.STATUS_REJECTED)

    def test_reject_requires_can_manage_financials(self):
        exp = Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('10.00'), purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        self.client_http.force_login(self.worker)
        r = self.client_http.post(f'/api/expenses/{exp.pk}/reject/')
        self.assertEqual(r.status_code, 403)

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
    def test_retry_sync_on_sync_failed(self, mock_push):
        _seed_payment_accounts()
        mock_push.return_value = '9001'
        exp = Expense.objects.create(
            entered_by=self.admin,
            amount=Decimal('100.00'), purchased_on=date(2026, 4, 9),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            status=Expense.STATUS_SYNC_FAILED,
        )
        self.client_http.force_login(self.admin)
        r = self.client_http.post(f'/api/expenses/{exp.pk}/retry-sync/')
        self.assertEqual(r.status_code, 200, r.content)
        exp.refresh_from_db()
        self.assertEqual(exp.status, Expense.STATUS_SYNCED)


class ExpenseDeleteTest(TestCase):
    def setUp(self):
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

    def test_delete_returns_200_with_json_body(self):
        exp = Expense.objects.create(
            entered_by=self.admin, purchased_by=self.admin,
            amount=Decimal('10.00'), purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        self.client_http.force_login(self.admin)
        r = self.client_http.delete(f'/api/expenses/{exp.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('message', r.json())
        self.assertFalse(Expense.objects.filter(pk=exp.pk).exists())


# NOTE: MaterialsBucketFlagTest removed in Phase C2. The
# /api/work-orders/{wo_pk}/materials/ endpoint with _use_materials_bucket
# flag no longer exists after WorkOrder removal. The bucket-task pattern
# at ExpenseService.find_or_create_materials_task is still available at
# the service layer (now job-scoped) and is exercised by service-layer
# tests in test_expense_service.py. A replacement job-scoped API
# endpoint for bucket-mode material creation can be added when the
# frontend requires it.


class ExpenseJobFieldTest(TestCase):
    """Expense.job is read directly and writable via the API."""

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{counter:04d}'})
        Configuration.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core')
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)
        self.contact = Contact.objects.create(first_name='T', last_name='C', email='c@t.com')
        self.job = Job.objects.create(job_number='JOB-A3-1', contact=self.contact)
        self.other_job = Job.objects.create(job_number='JOB-A3-2', contact=self.contact)
        self.client_http.force_login(self.admin)

    def _post(self, **extra):
        body = dict(
            amount='25.00', purchased_on='2026-04-01',
            accounting_category=self.cat.pk,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            purchased_by=self.admin.pk,
        )
        body.update(extra)
        return self.client_http.post(
            '/api/expenses/', data=body, content_type='application/json')

    def test_create_with_job_no_material(self):
        r = self._post(job=self.job.pk)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['job_id'], self.job.pk)
        self.assertEqual(r.json()['job_number'], 'JOB-A3-1')

    def test_overhead_expense_has_null_job(self):
        r = self._post()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNone(r.json()['job_id'])

    def test_patch_job(self):
        r = self._post(job=self.job.pk)
        eid = r.json()['id']
        r2 = self.client_http.patch(
            f'/api/expenses/{eid}/', data={'job': self.other_job.pk},
            content_type='application/json')
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.json()['job_id'], self.other_job.pk)

    def test_list_filter_by_job(self):
        self._post(job=self.job.pk)
        self._post(job=self.other_job.pk)
        r = self.client_http.get(f'/api/expenses/?job={self.job.pk}')
        self.assertEqual(r.status_code, 200)
        job_ids = {row['job_id'] for row in r.json()['results']}
        self.assertEqual(job_ids, {self.job.pk})


class ExpenseStockReceiptApiTest(TestCase):
    """POST new_material with an inventoried PLI → a stock receipt (QOH up, no material)."""

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        from apps.inventory.models import PriceListItem
        self.client_http = Client()
        self.cat = AccountingCategory.objects.create(code='SR', name='Stock')
        self.user = User.objects.create_user(username='w', password='x')
        self.contact = Contact.objects.create(first_name='T', last_name='C', email='c@t.com')
        self.job = Job.objects.create(job_number='JOB-SRA-1', contact=self.contact)
        self.pli = PriceListItem.objects.create(
            code='PLY', description='plywood', accounting_category=self.cat,
            is_inventoried=True, qty_on_hand=Decimal('7.00'))
        self.client_http.force_login(self.user)

    def test_inventoried_new_material_creates_stock_receipt(self):
        from apps.inventory.models import Material
        r = self.client_http.post('/api/expenses/', data={
            'amount': '73.33', 'purchased_on': '2026-04-01',
            'accounting_category': self.cat.pk,
            'payment_method': Expense.PAYMENT_METHOD_PERSONAL,
            'purchased_by': self.user.pk,
            'new_material': {'job_id': self.job.pk,
                             'price_list_item_id': self.pli.pk, 'quantity': '3'},
        }, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(Material.objects.filter(job=self.job).exists())  # no consumable
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10.00'))  # 7 + 3
