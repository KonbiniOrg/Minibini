from decimal import Decimal
from datetime import date
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError  # noqa: F401
from apps.core.models import Configuration, AccountingCategory
from apps.expenses.models import Expense, Reimbursement
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material
from apps.expenses.services import ExpenseService
from apps.qbo.models import QBOSyncLog
from apps.qbo.services import QBOExpenseSyncService

User = get_user_model()


class GetPaymentAccountsTest(TestCase):
    """QBOExpenseSyncService.get_payment_accounts pulls Bank/CC/OCA accounts."""

    @patch('apps.qbo.services.QBOService.get_client')
    def test_get_payment_accounts_returns_enabled_bank_cc_and_oca(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        def make_account(id_, name, acct_type):
            a = MagicMock()
            a.Id = id_
            a.Name = name
            a.AccountType = acct_type
            return a

        fake_bank = [
            make_account('42', 'BoA Business Checking', 'Bank'),
            make_account('43', 'BoA Savings', 'Bank'),
        ]
        fake_cc = [make_account('57', 'Amex Business', 'Credit Card')]
        fake_oca = [make_account('89', 'Petty Cash', 'Other Current Asset')]

        with patch('quickbooks.objects.account.Account.filter') as mock_filter:
            mock_filter.side_effect = lambda AccountType, Active, qb: {
                'Bank': fake_bank,
                'Credit Card': fake_cc,
                'Other Current Asset': fake_oca,
            }[AccountType]
            result = QBOExpenseSyncService.get_payment_accounts()

        ids = {a['qbo_account_id'] for a in result}
        self.assertEqual(ids, {'42', '43', '57', '89'})
        by_id = {a['qbo_account_id']: a for a in result}
        self.assertEqual(by_id['42']['account_type'], 'Bank')
        self.assertEqual(by_id['42']['display_name'], 'BoA Business Checking')
        self.assertEqual(by_id['57']['account_type'], 'Credit Card')
        self.assertEqual(by_id['89']['account_type'], 'Other Current Asset')

    def test_get_payment_accounts_raises_without_connection(self):
        with self.assertRaises(ValueError):
            QBOExpenseSyncService.get_payment_accounts()


class PaymentAccountsEndpointTest(TestCase):
    """GET /api/qbo/payment-accounts/ — wraps QBOExpenseSyncService."""

    def setUp(self):
        self.client_http = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(
            codename='can_manage_config', content_type__app_label='core',
        )
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

    def test_requires_authentication(self):
        r = self.client_http.get('/api/qbo/payment-accounts/')
        self.assertIn(r.status_code, (401, 403))

    def test_requires_can_manage_config(self):
        unpriv = User.objects.create_user(username='worker', password='testpass')
        self.client_http.force_login(unpriv)
        r = self.client_http.get('/api/qbo/payment-accounts/')
        self.assertEqual(r.status_code, 403)

    @patch('apps.qbo.services.QBOExpenseSyncService.get_payment_accounts')
    def test_returns_service_payload(self, mock_get):
        mock_get.return_value = [
            {'qbo_account_id': '42', 'display_name': 'BoA Checking', 'account_type': 'Bank'},
        ]
        self.client_http.force_login(self.admin)
        r = self.client_http.get('/api/qbo/payment-accounts/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {
            'payment_accounts': [
                {'qbo_account_id': '42', 'display_name': 'BoA Checking', 'account_type': 'Bank'},
            ]
        })

    @patch('apps.qbo.services.QBOExpenseSyncService.get_payment_accounts')
    def test_returns_400_when_not_connected(self, mock_get):
        mock_get.side_effect = ValueError('No active QBO connection')
        self.client_http.force_login(self.admin)
        r = self.client_http.get('/api/qbo/payment-accounts/')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {'error': 'No active QBO connection'})


class PushExpenseTest(TestCase):
    """Push a company-paid Expense as a QBO Purchase with one line."""

    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "42", "display_name": "BoA Checking", "account_type": "Bank"},'
                ' {"qbo_account_id": "57", "display_name": "Amex Business", "account_type": "Credit Card"},'
                ' {"qbo_account_id": "89", "display_name": "Petty Cash", "account_type": "Other Current Asset"}]'
            )},
        )
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', qbo_expense_account_id='500',
        )
        self.user = User.objects.create_user(username='worker', password='testpass')

    def _expense(self, **overrides):
        defaults = dict(
            entered_by=self.user,
            amount=Decimal('218.45'),
            purchased_on=date(2026, 4, 9),
            description='Sherwin-Williams paint',
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
        )
        defaults.update(overrides)
        return Expense.objects.create(**defaults)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_expense_stores_qbo_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_purchase = MagicMock()
        mock_purchase.Id = '9001'
        mock_purchase.save = MagicMock(return_value=mock_purchase)

        exp = self._expense()
        with patch.object(
            QBOExpenseSyncService, '_build_qbo_purchase_for_expense',
            return_value=mock_purchase,
        ):
            result = QBOExpenseSyncService.push_expense(exp)

        exp.refresh_from_db()
        self.assertEqual(exp.qbo_id, '9001')
        self.assertEqual(result, '9001')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_expense_skips_if_already_synced(self, mock_get_client):
        exp = self._expense(qbo_id='9001')
        result = QBOExpenseSyncService.push_expense(exp)
        self.assertEqual(result, '9001')
        mock_get_client.assert_not_called()

    def test_push_expense_requires_connection(self):
        exp = self._expense()
        with self.assertRaises(ValueError):
            QBOExpenseSyncService.push_expense(exp)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_expense_logs_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_purchase = MagicMock()
        mock_purchase.Id = '9001'
        mock_purchase.save = MagicMock(return_value=mock_purchase)
        exp = self._expense()
        with patch.object(
            QBOExpenseSyncService, '_build_qbo_purchase_for_expense',
            return_value=mock_purchase,
        ):
            QBOExpenseSyncService.push_expense(exp)
        log = QBOSyncLog.objects.get(entity_type='expense', entity_id=exp.pk)
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '9001')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_expense_logs_failure_and_raises(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_purchase = MagicMock()
        mock_purchase.save = MagicMock(side_effect=RuntimeError('boom'))
        exp = self._expense()
        with patch.object(
            QBOExpenseSyncService, '_build_qbo_purchase_for_expense',
            return_value=mock_purchase,
        ), self.assertRaises(RuntimeError):
            QBOExpenseSyncService.push_expense(exp)
        log = QBOSyncLog.objects.get(entity_type='expense', entity_id=exp.pk)
        self.assertEqual(log.status, 'failed')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_credit_card_payment_type(self, mock_get_client):
        exp = self._expense(payment_account_id='57')  # Amex = Credit Card
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_expense(exp)
        self.assertEqual(purchase.PaymentType, 'CreditCard')
        self.assertEqual(purchase.AccountRef.value, '57')
        self.assertEqual(len(purchase.Line), 1)
        self.assertEqual(float(purchase.Line[0].Amount), 218.45)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_bank_with_reference_is_check(self, mock_get_client):
        exp = self._expense(
            payment_account_id='42',  # BoA = Bank
            reference_number='1234',
        )
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_expense(exp)
        self.assertEqual(purchase.PaymentType, 'Check')
        self.assertEqual(purchase.DocNumber, '1234')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_bank_without_reference_has_no_payment_type(self, mock_get_client):
        exp = self._expense(payment_account_id='42', reference_number='')
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_expense(exp)
        # PaymentType left unset — QBO defaults to Cash for electronic transfers
        self.assertFalse(getattr(purchase, 'PaymentType', None))

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_oca_has_no_payment_type(self, mock_get_client):
        exp = self._expense(payment_account_id='89')  # Petty Cash = OCA
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_expense(exp)
        self.assertFalse(getattr(purchase, 'PaymentType', None))

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_private_note_tags_origin(self, mock_get_client):
        exp = self._expense()
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_expense(exp)
        self.assertIn('Minibini expense', purchase.PrivateNote)
        self.assertIn(str(exp.pk), purchase.PrivateNote)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_line_uses_accounting_category_account(self, mock_get_client):
        exp = self._expense()
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_expense(exp)
        line = purchase.Line[0]
        self.assertEqual(line.AccountBasedExpenseLineDetail.AccountRef.value, '500')


class UpdateExpenseTest(TestCase):
    """Update an already-synced expense — sparse update of QBO Purchase."""

    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
            )},
        )
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.exp = Expense.objects.create(
            entered_by=self.user,
            amount=Decimal('100.00'),
            purchased_on=date(2026, 4, 9),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            qbo_id='9001',
        )

    @patch('apps.qbo.services.QBOService.get_client')
    def test_update_expense_fetches_and_saves(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        existing = MagicMock()
        existing.Id = '9001'
        existing.Line = []
        existing.save = MagicMock(return_value=existing)

        with patch('quickbooks.objects.purchase.Purchase.get', return_value=existing) as mock_get:
            QBOExpenseSyncService.update_expense(self.exp)

        mock_get.assert_called_once_with('9001', qb=mock_client)
        existing.save.assert_called_once()

    def test_update_expense_raises_without_qbo_id(self):
        self.exp.qbo_id = ''
        self.exp.save(update_fields=['qbo_id'])
        with self.assertRaises(ValueError):
            QBOExpenseSyncService.update_expense(self.exp)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_update_expense_logs_success(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        existing = MagicMock()
        existing.Id = '9001'
        existing.save = MagicMock(return_value=existing)
        with patch('quickbooks.objects.purchase.Purchase.get', return_value=existing):
            QBOExpenseSyncService.update_expense(self.exp)
        log = QBOSyncLog.objects.get(entity_type='expense', action='update')
        self.assertEqual(log.status, 'success')


class VoidExpenseTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
            )},
        )
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.exp = Expense.objects.create(
            entered_by=self.user,
            amount=Decimal('100.00'),
            purchased_on=date(2026, 4, 9),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            qbo_id='9001',
        )

    @patch('apps.qbo.services.QBOService.get_client')
    def test_void_expense_deletes_qbo_purchase(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        existing = MagicMock()
        existing.delete = MagicMock()
        with patch('quickbooks.objects.purchase.Purchase.get', return_value=existing):
            QBOExpenseSyncService.void_expense(self.exp)
        existing.delete.assert_called_once()

    def test_void_expense_noop_without_qbo_id(self):
        self.exp.qbo_id = ''
        self.exp.save(update_fields=['qbo_id'])
        QBOExpenseSyncService.void_expense(self.exp)  # no exception

    @patch('apps.qbo.services.QBOService.get_client')
    def test_void_expense_logs_failure_but_does_not_raise(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        existing = MagicMock()
        existing.delete = MagicMock(side_effect=RuntimeError('qbo down'))
        with patch('quickbooks.objects.purchase.Purchase.get', return_value=existing):
            QBOExpenseSyncService.void_expense(self.exp)  # must not raise
        log = QBOSyncLog.objects.get(entity_type='expense', action='delete')
        self.assertEqual(log.status, 'failed')


class PushReimbursementTest(TestCase):
    """Push a reimbursement batch as a QBO Purchase with N lines."""

    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "42", "display_name": "BoA Checking", "account_type": "Bank"}]'
            )},
        )
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', qbo_expense_account_id='500',
        )
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')

        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            reference_number='1234',
            created_by=self.admin,
        )
        for amt in ('47.50', '62.00', '28.75'):
            Expense.objects.create(
                entered_by=self.worker,
                purchased_by=self.worker,
                amount=Decimal(amt),
                purchased_on=date(2026, 4, 5),
                accounting_category=self.cat,
                payment_method=Expense.PAYMENT_METHOD_PERSONAL,
                status=Expense.STATUS_REIMBURSED,
                reimbursement=self.batch,
            )

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_reimbursement_stores_qbo_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_purchase = MagicMock()
        mock_purchase.Id = '9100'
        mock_purchase.save = MagicMock(return_value=mock_purchase)

        with patch.object(
            QBOExpenseSyncService, '_build_qbo_purchase_for_reimbursement',
            return_value=mock_purchase,
        ):
            result = QBOExpenseSyncService.push_reimbursement(self.batch)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qbo_id, '9100')
        self.assertEqual(result, '9100')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_reimbursement_skips_if_already_synced(self, mock_get_client):
        self.batch.qbo_id = '9100'
        self.batch.save(update_fields=['qbo_id'])
        result = QBOExpenseSyncService.push_reimbursement(self.batch)
        self.assertEqual(result, '9100')
        mock_get_client.assert_not_called()

    def test_push_reimbursement_requires_connection(self):
        with self.assertRaises(ValueError):
            QBOExpenseSyncService.push_reimbursement(self.batch)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_has_n_lines_one_per_expense(self, mock_get_client):
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_reimbursement(self.batch)
        self.assertEqual(len(purchase.Line), 3)
        amounts = sorted(float(l.Amount) for l in purchase.Line)
        self.assertEqual(amounts, [28.75, 47.50, 62.00])

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_uses_batch_payment_account_and_ref(self, mock_get_client):
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_reimbursement(self.batch)
        self.assertEqual(purchase.AccountRef.value, '42')
        # Bank + reference# → Check
        self.assertEqual(purchase.PaymentType, 'Check')
        self.assertEqual(purchase.DocNumber, '1234')
        self.assertEqual(purchase.TxnDate, '2026-04-11')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_build_qbo_purchase_private_note_tags_origin_and_user(self, mock_get_client):
        purchase = QBOExpenseSyncService._build_qbo_purchase_for_reimbursement(self.batch)
        self.assertIn('Reimbursement', purchase.PrivateNote)
        self.assertIn('worker', purchase.PrivateNote)
        self.assertIn(str(self.batch.pk), purchase.PrivateNote)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_reimbursement_logs_success(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        mock_purchase = MagicMock()
        mock_purchase.Id = '9100'
        mock_purchase.save = MagicMock(return_value=mock_purchase)
        with patch.object(
            QBOExpenseSyncService, '_build_qbo_purchase_for_reimbursement',
            return_value=mock_purchase,
        ):
            QBOExpenseSyncService.push_reimbursement(self.batch)
        log = QBOSyncLog.objects.get(entity_type='reimbursement', entity_id=self.batch.pk)
        self.assertEqual(log.status, 'success')


class UpdateReimbursementTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "42", "display_name": "BoA Checking", "account_type": "Bank"}]'
            )},
        )
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
            qbo_id='9100',
        )
        Expense.objects.create(
            entered_by=self.worker, purchased_by=self.worker,
            amount=Decimal('50.00'), purchased_on=date(2026, 4, 5),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            status=Expense.STATUS_REIMBURSED,
            reimbursement=self.batch,
        )

    @patch('apps.qbo.services.QBOService.get_client')
    def test_update_reimbursement_fetches_and_saves(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        existing = MagicMock()
        existing.Id = '9100'
        existing.Line = []
        existing.save = MagicMock(return_value=existing)
        with patch('quickbooks.objects.purchase.Purchase.get', return_value=existing):
            QBOExpenseSyncService.update_reimbursement(self.batch)
        existing.save.assert_called_once()
        self.assertEqual(len(existing.Line), 1)

    def test_update_reimbursement_raises_without_qbo_id(self):
        self.batch.qbo_id = ''
        self.batch.save(update_fields=['qbo_id'])
        with self.assertRaises(ValueError):
            QBOExpenseSyncService.update_reimbursement(self.batch)


class VoidReimbursementTest(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        self.batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
            qbo_id='9100',
        )

    @patch('apps.qbo.services.QBOService.get_client')
    def test_void_reimbursement_deletes_qbo_purchase(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        existing = MagicMock()
        existing.delete = MagicMock()
        with patch('quickbooks.objects.purchase.Purchase.get', return_value=existing):
            QBOExpenseSyncService.void_reimbursement(self.batch)
        existing.delete.assert_called_once()

    def test_void_reimbursement_noop_without_qbo_id(self):
        self.batch.qbo_id = ''
        self.batch.save(update_fields=['qbo_id'])
        QBOExpenseSyncService.void_reimbursement(self.batch)  # no exception


class SFMOMAIntegrationTest(TestCase):
    """End-to-end scenarios for the SFMOMA paint use case."""

    def setUp(self):
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'},
        )
        Configuration.objects.update_or_create(
            key='job_counter', defaults={'value': '0'},
        )
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': (
                '[{"qbo_account_id": "57", "display_name": "Amex", "account_type": "Credit Card"}]'
            )},
        )
        self.user = User.objects.create_user(username='admin', password='testpass')
        self.cat = AccountingCategory.objects.create(
            code='MAT', name='Materials', qbo_expense_account_id='500',
        )
        contact = Contact.objects.create(
            first_name='SFMOMA', last_name='Admin',
            email='admin@sfmoma.org', mobile_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='SFMOMA', default_contact=contact,
        )
        contact.business = self.business
        contact.save()
        self.job = Job.objects.create(contact=contact, job_number='JOB-2026-0042')
        self.scheme = RateScheme.objects.create(
            name='S-sfmoma', algorithm=RateScheme.FLAT_FEE,
            rate=1, unit_label='ea', accounting_category=self.cat,
        )

    @patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
    def test_two_new_material_expenses_create_two_taskless_materials(self, mock_push):
        """Two new-material expenses on the same Job each create a distinct
        task-less Material; no 'Materials' placeholder task is created."""
        mock_push.return_value = '9001'

        # First expense — creates task-less material via new_material
        exp1 = ExpenseService.submit(
            entered_by=self.user,
            amount=Decimal('218.45'),
            purchased_on=date(2026, 4, 9),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            new_material={
                'job_id': self.job.pk,
                'description': 'Acrylic paint 1gal',
                'quantity': 2,
                'price': '218.45',
            },
        )

        # Second expense — creates a second task-less material
        exp2 = ExpenseService.submit(
            entered_by=self.user,
            amount=Decimal('28.50'),
            purchased_on=date(2026, 4, 10),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='57',
            new_material={
                'job_id': self.job.pk,
                'description': 'Roller brushes',
                'quantity': 3,
                'price': '28.50',
            },
        )

        # Assert: no 'Materials' placeholder task exists
        self.assertFalse(Task.objects.filter(job=self.job, name='Materials').exists())

        # Assert: two separate task-less materials, each linked to the job
        mats = Material.objects.filter(job=self.job, task__isnull=True).order_by('material_id')
        self.assertEqual(mats.count(), 2)
        self.assertEqual(mats[0].description, 'Acrylic paint 1gal')
        self.assertEqual(mats[1].description, 'Roller brushes')

        # Both expenses pushed to QBO
        self.assertEqual(mock_push.call_count, 2)
        self.assertEqual(exp1.qbo_sync_status, Expense.SYNC_SYNCED)
        self.assertEqual(exp2.qbo_sync_status, Expense.SYNC_SYNCED)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_full_company_paid_push_happy_path(self, mock_get_client):
        """The SFMOMA paint story: Dana buys paint on company card, expense pushes."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_purchase = MagicMock()
        mock_purchase.Id = '9001'
        mock_purchase.save = MagicMock(return_value=mock_purchase)

        with patch.object(
            QBOExpenseSyncService, '_build_qbo_purchase_for_expense',
            wraps=QBOExpenseSyncService._build_qbo_purchase_for_expense,
        ) as wrap_build, patch(
            'quickbooks.objects.purchase.Purchase',
            return_value=mock_purchase,
        ):
            exp = ExpenseService.submit(
                entered_by=self.user,
                amount=Decimal('218.45'),
                purchased_on=date(2026, 4, 9),
                description='Sherwin-Williams paint',
                accounting_category=self.cat,
                payment_method=Expense.PAYMENT_METHOD_COMPANY,
                payment_account_id='57',
            )

        exp.refresh_from_db()
        self.assertEqual(exp.qbo_sync_status, Expense.SYNC_SYNCED)
        self.assertEqual(exp.qbo_id, '9001')
        wrap_build.assert_called_once()
