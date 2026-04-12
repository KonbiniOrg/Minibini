from datetime import date
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.expenses.models import Reimbursement

User = get_user_model()


class ReimbursementModelTest(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')

    def test_create_reimbursement_defaults_pending(self):
        r = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
        )
        self.assertEqual(r.status, Reimbursement.STATUS_PENDING)
        self.assertEqual(r.reference_number, '')
        self.assertEqual(r.notes, '')
        self.assertEqual(r.qbo_id, '')

    def test_status_choices_enumerated(self):
        statuses = [s for s, _ in Reimbursement.STATUS_CHOICES]
        self.assertEqual(set(statuses), {'pending', 'synced', 'sync_failed'})

    def test_table_name(self):
        self.assertEqual(Reimbursement._meta.db_table, 'reimbursements')
