"""commit_contacts: terms → customers → vendors, with same-name merge.
commit_terms: the standalone Settings → Business terms panel."""
from django.test import TestCase

from apps.contacts.models import Business, Contact, PaymentTerms
from apps.qbo.import_services import QBOImportCommitService, QBOImportState


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
                     'company_name': 'Moore Newton',
                     'email': 'sales@moorenewton.com',
                     'phone': '', 'action': 'create'}],
    }
    payload.update(overrides)
    return payload


class CommitTermsTest(TestCase):
    def setUp(self):
        from tests.test_qbo_import_state import store_snapshot
        store_snapshot()

    def test_create_update_and_auto_dismiss(self):
        result = QBOImportCommitService.commit_terms([
            {'qbo_id': '3', 'name': 'Net 30', 'due_days': 30,
             'action': 'create'}])
        self.assertEqual(result['created'], 1)
        term = PaymentTerms.objects.get(qbo_id='3')
        self.assertEqual(term.name, 'Net 30')
        self.assertEqual(term.days, 30)
        # Snapshot's only term is now imported → area auto-dismisses.
        self.assertIn('terms', QBOImportState.dismissed())
        result = QBOImportCommitService.commit_terms([
            {'qbo_id': '3', 'name': 'Net 30 EOM', 'due_days': 30,
             'action': 'update'}])
        self.assertEqual(result['updated'], 1)
        term.refresh_from_db()
        self.assertEqual(term.name, 'Net 30 EOM')

    def test_endpoint_requires_config_atom(self):
        from django.contrib.auth.models import Permission
        from rest_framework.test import APIClient
        from apps.core.models import User
        client = APIClient()
        user = User.objects.create_user(username='jobs1', password='x')
        user.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        client.force_authenticate(user=User.objects.get(pk=user.pk))
        resp = client.post('/api/qbo/import/commit/terms/', {
            'rows': [{'qbo_id': '3', 'name': 'Net 30', 'due_days': 30,
                      'action': 'create'}]}, format='json')
        self.assertEqual(resp.status_code, 403)
        user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        client.force_authenticate(user=User.objects.get(pk=user.pk))
        resp = client.post('/api/qbo/import/commit/terms/', {
            'rows': [{'qbo_id': '3', 'name': 'Net 30', 'due_days': 30,
                      'action': 'create'}]}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['created'], 1)


def _customer(**overrides):
    row = {'qbo_id': '72', 'display_name': 'Blah Company',
           'company_name': 'Blah Company', 'given_name': 'Bea',
           'family_name': 'Blah', 'email': 'bea@blah.com',
           'phone': '', 'term_qbo_id': '', 'action': 'create'}
    row.update(overrides)
    return row


class CommitContactsSkipTest(TestCase):
    """Un-importable rows are skipped and reported, never a 500.

    Konbini requires a unique, non-blank contact email and a unique
    business name; QBO doesn't. The commit imports what it can and
    returns {'name', 'reason'} entries for the rest."""

    def test_duplicate_email_with_existing_contact(self):
        Contact.objects.create(first_name='Bulb', last_name='Co',
                               email='bea@blah.com')
        result = QBOImportCommitService.commit_contacts(
            {'customers': [_customer()]})
        self.assertEqual(result['customers']['created'], 0)
        skip = result['customers']['skipped'][0]
        self.assertEqual(skip['name'], 'Blah Company')
        self.assertIn('duplicate email', skip['reason'])
        self.assertIn('Bulb Co', skip['reason'])
        self.assertFalse(
            Business.objects.filter(business_name='Blah Company').exists())

    def test_duplicate_email_within_batch(self):
        result = QBOImportCommitService.commit_contacts({'customers': [
            _customer(),
            _customer(qbo_id='73', display_name='Blah Company - East',
                      company_name='Blah Company East'),
        ]})
        self.assertEqual(result['customers']['created'], 1)
        skip = result['customers']['skipped'][0]
        self.assertEqual(skip['name'], 'Blah Company - East')
        self.assertIn('duplicate email', skip['reason'])
        self.assertIn('Blah Company', skip['reason'])

    def test_missing_email_skipped(self):
        result = QBOImportCommitService.commit_contacts(
            {'customers': [_customer(email='')]})
        self.assertEqual(result['customers']['created'], 0)
        skip = result['customers']['skipped'][0]
        self.assertIn('no email', skip['reason'])

    def test_duplicate_business_name_skipped(self):
        contact = Contact.objects.create(
            first_name='X', last_name='Y', email='other@blah.com')
        Business.objects.create(business_name='Blah Company',
                                default_contact=contact)
        result = QBOImportCommitService.commit_contacts(
            {'customers': [_customer()]})
        self.assertEqual(result['customers']['created'], 0)
        self.assertIn('business named',
                      result['customers']['skipped'][0]['reason'])

    def test_update_with_blank_email_keeps_existing(self):
        QBOImportCommitService.commit_contacts({'customers': [_customer()]})
        result = QBOImportCommitService.commit_contacts({'customers': [
            _customer(action='update', email='')]})
        self.assertEqual(result['customers']['updated'], 1)
        business = Business.objects.get(business_name='Blah Company')
        self.assertEqual(business.default_contact.email, 'bea@blah.com')

    def test_update_email_collision_skipped(self):
        QBOImportCommitService.commit_contacts({'customers': [_customer()]})
        Contact.objects.create(first_name='Taken', last_name='Contact',
                               email='taken@x.com')
        result = QBOImportCommitService.commit_contacts({'customers': [
            _customer(action='update', email='taken@x.com')]})
        self.assertEqual(result['customers']['updated'], 0)
        self.assertIn('duplicate email',
                      result['customers']['skipped'][0]['reason'])

    def test_vendor_missing_email_skipped_but_merge_needs_none(self):
        result = QBOImportCommitService.commit_contacts({'vendors': [
            {'qbo_id': '82', 'display_name': 'No Mail Vendor',
             'company_name': 'No Mail Vendor', 'email': '', 'phone': '',
             'action': 'create'}]})
        self.assertEqual(result['vendors']['created'], 0)
        self.assertIn('no email', result['vendors']['skipped'][0]['reason'])
        # Merge-by-name adopts the existing business — no contact is
        # created, so no email is needed.
        contact = Contact.objects.create(
            first_name='A', last_name='B', email='a@acme.com')
        Business.objects.create(business_name='Acme Corp',
                                default_contact=contact)
        result = QBOImportCommitService.commit_contacts({'vendors': [
            {'qbo_id': '83', 'display_name': 'Acme Corp',
             'company_name': 'Acme Corp', 'email': '', 'phone': '',
             'action': 'create'}]})
        self.assertEqual(result['vendors']['created'], 1)
        self.assertEqual(result['vendors']['skipped'], [])
        self.assertEqual(
            Business.objects.get(business_name='Acme Corp').qbo_vendor_id,
            '83')


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
