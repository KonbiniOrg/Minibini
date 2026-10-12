# tests/test_qbo_status_sync.py
from django.utils import timezone
from unittest.mock import MagicMock, patch
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Business, Contact
from apps.contacts.services import ContactService
from apps.qbo.models import QBOConnection, QBOSyncLog
from tests.test_contacts_status import make_business


def connect():
    now = timezone.now()
    QBOConnection.objects.create(
        realm_id='r1', access_token='a', refresh_token='r', is_active=True,
        access_token_expires_at=now + timezone.timedelta(hours=1),
        refresh_token_expires_at=now + timezone.timedelta(days=100),
        connected_at=now)


class PushStatusTest(TestCase):
    def setUp(self):
        connect()
        self.biz, self.dc, _ = make_business('QCo')
        self.biz.qbo_customer_id = '71'
        self.biz.qbo_vendor_id = '81'
        self.biz.save()

    def _fake_entity(self):
        e = MagicMock(); e.Id = '71'; e.Active = True
        return e

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_business_deactivate_pushes_customer_and_vendor(self, _client):
        cust, vend = self._fake_entity(), self._fake_entity()
        with patch('quickbooks.objects.customer.Customer.get', return_value=cust), \
             patch('quickbooks.objects.vendor.Vendor.get', return_value=vend):
            ContactService.deactivate_business(self.biz)
        self.assertFalse(cust.Active); cust.save.assert_called_once()
        self.assertFalse(vend.Active); vend.save.assert_called_once()
        self.biz.refresh_from_db(); self.assertFalse(self.biz.is_active)
        self.assertEqual(QBOSyncLog.objects.filter(action='deactivate', status='success').count(), 2)
        # cascade-flipped contacts never push
        self.assertFalse(QBOSyncLog.objects.filter(entity_type='contact_customer').exists())

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_qbo_refusal_rolls_back_local_flip_and_logs_failure(self, _client):
        cust = self._fake_entity(); cust.save.side_effect = Exception('Customer has an open balance')
        with patch('quickbooks.objects.customer.Customer.get', return_value=cust):
            with self.assertRaises(ValidationError) as cm:
                ContactService.deactivate_business(self.biz)
        self.assertIn('QuickBooks refused to deactivate QCo', str(cm.exception))
        self.assertIn('open balance', str(cm.exception))
        self.biz.refresh_from_db(); self.assertTrue(self.biz.is_active)
        self.dc.refresh_from_db(); self.assertTrue(self.dc.is_active)
        self.assertTrue(QBOSyncLog.objects.filter(action='deactivate', status='failed').exists())

    def test_no_connection_skips_push(self):
        QBOConnection.objects.update(is_active=False)
        with patch('apps.qbo.services.QBOService.get_client') as gc:
            ContactService.deactivate_business(self.biz)
        gc.assert_not_called()
        self.biz.refresh_from_db(); self.assertFalse(self.biz.is_active)

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_no_qbo_id_skips_push(self, client):
        b2, _, _ = make_business('NoId')
        with patch('quickbooks.objects.customer.Customer.get') as get:
            ContactService.deactivate_business(b2)
        get.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_individual_contact_pushes_as_customer(self, _client):
        c = Contact.objects.create(first_name='Solo', last_name='Q', email='soloq@x.test', qbo_customer_id='99')
        cust = self._fake_entity()
        with patch('quickbooks.objects.customer.Customer.get', return_value=cust):
            ContactService.deactivate_contact(c)
            ContactService.reactivate_contact(c)
        self.assertEqual(QBOSyncLog.objects.filter(entity_type='contact_customer').count(), 2)
        self.assertTrue(QBOSyncLog.objects.filter(action='reactivate').exists())

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_push_to_qbo_false_skips(self, _client):
        with patch('quickbooks.objects.customer.Customer.get') as get:
            ContactService.deactivate_business(self.biz, push_to_qbo=False)
        get.assert_not_called()
