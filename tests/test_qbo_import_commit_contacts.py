"""commit_contacts: terms → customers → vendors, with same-name merge."""
from django.test import TestCase

from apps.contacts.models import Business, Contact, PaymentTerms
from apps.qbo.import_services import QBOImportCommitService


def _payload(**overrides):
    payload = {
        'terms': [{'qbo_id': '3', 'name': 'Net 30', 'due_days': 30,
                   'action': 'create'}],
        'customers': [{'qbo_id': '71', 'display_name': 'Acme Corp',
                       'company_name': 'Acme Corp', 'given_name': 'Jo',
                       'family_name': 'Acme', 'email': 'jo@acme.com',
                       'phone': '555-1000', 'term_qbo_id': '3',
                       'action': 'create'}],
        'vendors': [{'qbo_id': '81', 'display_name': 'Moore Newton',
                     'company_name': 'Moore Newton', 'email': '',
                     'phone': '', 'action': 'create'}],
    }
    payload.update(overrides)
    return payload


class CommitContactsTest(TestCase):
    def test_full_create_wires_terms_and_ids(self):
        result = QBOImportCommitService.commit_contacts(_payload())
        self.assertEqual(result['terms']['created'], 1)
        self.assertEqual(result['customers']['created'], 1)
        self.assertEqual(result['vendors']['created'], 1)
        business = Business.objects.get(business_name='Acme Corp')
        self.assertEqual(business.qbo_customer_id, '71')
        self.assertEqual(business.terms.qbo_id, '3')
        self.assertEqual(business.default_contact.first_name, 'Jo')
        self.assertEqual(business.default_contact.email, 'jo@acme.com')
        vendor = Business.objects.get(business_name='Moore Newton')
        self.assertEqual(vendor.qbo_vendor_id, '81')

    def test_individual_customer_becomes_bare_contact(self):
        payload = _payload(customers=[{
            'qbo_id': '72', 'display_name': 'Hugo Solo', 'company_name': '',
            'given_name': 'Hugo', 'family_name': 'Solo',
            'email': 'hugo@solo.com', 'phone': '', 'term_qbo_id': '',
            'action': 'create'}], vendors=[])
        QBOImportCommitService.commit_contacts(payload)
        contact = Contact.objects.get(qbo_customer_id='72')
        self.assertEqual(contact.first_name, 'Hugo')
        self.assertIsNone(contact.business)

    def test_vendor_merges_onto_same_named_business(self):
        QBOImportCommitService.commit_contacts(_payload(vendors=[]))
        payload = _payload(terms=[], customers=[], vendors=[{
            'qbo_id': '82', 'display_name': 'Acme Corp',
            'company_name': 'Acme Corp', 'email': '', 'phone': '',
            'action': 'create'}])
        QBOImportCommitService.commit_contacts(payload)
        self.assertEqual(
            Business.objects.filter(business_name='Acme Corp').count(), 1)
        business = Business.objects.get(business_name='Acme Corp')
        self.assertEqual(business.qbo_customer_id, '71')
        self.assertEqual(business.qbo_vendor_id, '82')

    def test_update_overwrites_mirrored_fields(self):
        QBOImportCommitService.commit_contacts(_payload(vendors=[]))
        payload = _payload(terms=[], vendors=[], customers=[{
            'qbo_id': '71', 'display_name': 'Acme Corp',
            'company_name': 'Acme Corp', 'given_name': 'Jo',
            'family_name': 'Acme', 'email': 'new@acme.com', 'phone': '555-2000',
            'term_qbo_id': '3', 'action': 'update'}])
        result = QBOImportCommitService.commit_contacts(payload)
        self.assertEqual(result['customers']['updated'], 1)
        business = Business.objects.get(qbo_customer_id='71')
        self.assertEqual(business.default_contact.email, 'new@acme.com')
