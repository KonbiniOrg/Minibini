from rest_framework.test import APIClient
from rest_framework import status
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Contact, Business, PaymentTerms


class ContactAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_contacts(self):
        response = self.client.get('/api/contacts/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_search_matches_business_name(self):
        match = Contact.objects.create(first_name='Pat', last_name='Quinn', email='pat.quinn@example.com')
        biz = Business.objects.create(
            business_name='Zylotech Industries', default_contact=match)
        match.business = biz
        match.save()
        other = Contact.objects.create(first_name='Sam', last_name='Reed', email='sam.reed@example.com')
        response = self.client.get('/api/contacts/?search=Zylotech')
        self.assertEqual(response.status_code, 200)
        ids = [c['contact_id'] for c in response.data['results']]
        self.assertIn(match.contact_id, ids)
        self.assertNotIn(other.contact_id, ids)

    def test_create_contact(self):
        response = self.client.post('/api/contacts/', {
            'first_name': 'New',
            'last_name': 'Contact',
            'email': 'new@example.com',
            'phones': [{'number': '555-000-0000', 'label': 'mobile'}],
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_create_contact_with_business_id_persists_association(self):
        dc = Contact.objects.create(first_name='DC', last_name='')
        biz = Business.objects.create(business_name='Acme Steel', default_contact=dc)
        response = self.client.post('/api/contacts/', {
            'first_name': 'Linked',
            'last_name': 'Contact',
            'email': 'linked@example.com',
            'phones': [{'number': '555-111-2222', 'label': 'mobile'}],
            'business_id': biz.business_id,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        created = Contact.objects.get(contact_id=response.data['contact_id'])
        self.assertEqual(created.business_id, biz.business_id)

    def test_create_contact_with_duplicate_email_returns_409_with_existing_contact(self):
        existing = Contact.objects.create(
            first_name='Existing', last_name='Person',
            email='dupe@example.com', phones=[{'number': '555-999-0000', 'label': 'mobile'}],
        )
        response = self.client.post('/api/contacts/', {
            'first_name': 'New',
            'last_name': 'Person',
            'email': 'dupe@example.com',
            'phones': [{'number': '555-000-0000', 'label': 'mobile'}],
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'duplicate_email')
        self.assertEqual(response.data['existing_contact']['contact_id'], existing.contact_id)
        self.assertFalse(Contact.objects.filter(email='new@example.com').exists())

    def test_create_contact_with_duplicate_email_case_insensitive(self):
        Contact.objects.create(
            first_name='Existing', last_name='Person',
            email='Dupe@Example.com', phones=[{'number': '555-999-0000', 'label': 'mobile'}],
        )
        response = self.client.post('/api/contacts/', {
            'first_name': 'New',
            'last_name': 'Person',
            'email': 'dupe@example.com',
            'phones': [{'number': '555-000-0000', 'label': 'mobile'}],
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'duplicate_email')

    def test_retrieve_contact(self):
        contact = Contact.objects.first()
        response = self.client.get(f'/api/contacts/{contact.pk}/')
        self.assertEqual(response.status_code, 200)

    def test_update_contact(self):
        contact = Contact.objects.first()
        response = self.client.patch(f'/api/contacts/{contact.pk}/', {
            'first_name': 'Updated',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['first_name'], 'Updated')

    def test_delete_contact_without_confirm_returns_impact(self):
        contact = Contact.objects.first()
        response = self.client.delete(f'/api/contacts/{contact.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('confirm_required', response.data)

    def test_delete_contact_with_confirm(self):
        contact = Contact.objects.create(
            first_name='Delete', last_name='Me',
            email='delete@example.com', phones=[{'number': '555-999-9999', 'label': 'mobile'}],
        )
        response = self.client.delete(f'/api/contacts/{contact.pk}/?confirm=true')
        self.assertEqual(response.status_code, 200)


class BusinessAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_businesses(self):
        response = self.client.get('/api/businesses/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_business(self):
        business = Business.objects.first()
        response = self.client.get(f'/api/businesses/{business.pk}/')
        self.assertEqual(response.status_code, 200)

    def test_create_business_with_duplicate_name_returns_409_with_existing_business(self):
        dc = Contact.objects.create(
            first_name='DC', last_name='', email='dc@example.com', phones=[{'number': '555-1234', 'label': 'work'}],
        )
        existing = Business.objects.create(business_name='Argon.AI', default_contact=dc)
        new_contact = Contact.objects.create(
            first_name='New', last_name='Contact',
            email='new-contact@example.com', phones=[{'number': '555-000-0000', 'label': 'mobile'}],
        )
        response = self.client.post('/api/businesses/', {
            'business_name': 'Argon.AI',
            'default_contact_id': new_contact.contact_id,
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'duplicate_business_name')
        self.assertEqual(response.data['existing_business']['business_id'], existing.business_id)
        new_contact.refresh_from_db()
        self.assertIsNone(new_contact.business)

    def test_create_business_with_duplicate_name_case_insensitive(self):
        dc = Contact.objects.create(
            first_name='DC', last_name='', email='dc2@example.com', phones=[{'number': '555-1234', 'label': 'work'}],
        )
        Business.objects.create(business_name='Argon.AI', default_contact=dc)
        new_contact = Contact.objects.create(
            first_name='New', last_name='Contact',
            email='new-contact2@example.com', phones=[{'number': '555-000-0000', 'label': 'mobile'}],
        )
        response = self.client.post('/api/businesses/', {
            'business_name': 'argon.ai',
            'default_contact_id': new_contact.contact_id,
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'duplicate_business_name')

    def test_check_name_reports_existing_business(self):
        dc = Contact.objects.create(
            first_name='DC', last_name='', email='dc3@example.com', phones=[{'number': '555-1234', 'label': 'work'}],
        )
        existing = Business.objects.create(business_name='Argon.AI', default_contact=dc)
        response = self.client.get('/api/businesses/check-name/?name=argon.ai')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['exists'])
        self.assertEqual(response.data['business']['business_id'], existing.business_id)

    def test_check_name_reports_no_conflict(self):
        response = self.client.get('/api/businesses/check-name/?name=Nobody Yet Inc')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['exists'])
        self.assertIsNone(response.data['business'])

    def test_set_default_contact(self):
        business = Business.objects.first()
        contact = Contact.objects.filter(business=business).first()
        if contact:
            response = self.client.post(
                f'/api/businesses/{business.pk}/set-default-contact/',
                {'contact_id': contact.pk}, format='json'
            )
            self.assertEqual(response.status_code, 200)


class PaymentTermsAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_payment_terms(self):
        response = self.client.get('/api/payment-terms/')
        self.assertEqual(response.status_code, 200)

    def test_payment_terms_carry_name_days_qbo_id(self):
        from apps.contacts.models import PaymentTerms
        term = PaymentTerms.objects.create(name='Net 30', days=30, qbo_id='7')
        response = self.client.get('/api/payment-terms/')
        rows = response.data['results'] if isinstance(response.data, dict) else response.data
        row = next(r for r in rows if r['term_id'] == term.pk)
        self.assertEqual(row['name'], 'Net 30')
        self.assertEqual(row['days'], 30)
        self.assertEqual(str(term), 'Net 30')


class CustomerFinancialsAPITest(BaseTestCase):
    """The contact/business `financials` rollup and the job-summary rows the
    detail pages render (contacts UI redesign, 2026-10-10)."""

    def setUp(self):
        super().setUp()
        from datetime import timedelta
        from decimal import Decimal
        from django.utils import timezone
        from apps.jobs.models import Job
        from apps.invoicing.models import Invoice, InvoiceLineItem

        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(
            first_name='Dana', last_name='Whitfield', email='dana@harbor.test',
            phones=[{'number': '555-0147', 'label': 'work'}, {'number': '555-0162', 'label': 'mobile'}])
        self.business = Business.objects.create(
            business_name='Harbor Light', default_contact=self.contact)
        self.contact.business = self.business
        self.contact.save()
        self.sibling = Contact.objects.create(
            first_name='Marcus', last_name='Lee', email='marcus@harbor.test',
            business=self.business, phones=[{'number': '555-0171', 'label': 'work'}])

        now = timezone.now()
        self.t_first = now - timedelta(days=400)
        self.t_mid = now - timedelta(days=100)
        self.t_last = now - timedelta(days=10)
        # The endpoint reports local calendar dates.
        self.d_first = timezone.localtime(self.t_first).date().isoformat()
        self.d_last = timezone.localtime(self.t_last).date().isoformat()

        def job(contact, number, status, created, start=None):
            return Job.objects.create(
                job_number=number, name=number, status=status, contact=contact,
                created_date=created, start_date=start)

        # Dana: one open job (started most recently), one completed job.
        self.open_job = job(self.contact, 'JOB-CF-1', Job.STATUS_IN_PROGRESS,
                            self.t_mid, start=self.t_last)
        self.closed_job = job(self.contact, 'JOB-CF-2', Job.STATUS_COMPLETED,
                              self.t_first)
        # Created via objects.create, so completed_date isn't auto-stamped;
        # closed jobs only join the rolling window with a recent one.
        self.closed_job.completed_date = now - timedelta(days=30)
        self.closed_job.save()
        # Marcus: a draft job with no start date (counts as open for the business).
        self.sibling_job = job(self.sibling, 'JOB-CF-3', Job.STATUS_DRAFT, self.t_mid)

        def invoice(job, number, status, amount, paid=None):
            inv = Invoice.objects.create(
                job=job, invoice_number=number, status=status,
                qbo_amount_paid=paid)
            InvoiceLineItem.objects.create(
                invoice=inv, qty=Decimal('1'), price=Decimal(str(amount)))
            return inv

        invoice(self.open_job, 'INV-CF-1', Invoice.STATUS_PARTLY_PAID, 1000, paid='250.00')
        invoice(self.closed_job, 'INV-CF-2', Invoice.STATUS_PAID, 400, paid='400.00')
        invoice(self.open_job, 'INV-CF-3', Invoice.STATUS_DRAFT, 500)
        invoice(self.sibling_job, 'INV-CF-4', Invoice.STATUS_OPEN, 300)

    def test_contact_financials_rollup(self):
        r = self.client.get(f'/api/contacts/{self.contact.contact_id}/financials/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['open_jobs'], 1)
        # partly-paid 1000 - 250; the paid and draft invoices don't count.
        self.assertEqual(r.data['outstanding'], '750.00')
        self.assertEqual(r.data['first_job_date'], self.d_first)
        self.assertEqual(r.data['last_job_start'], self.d_last)
        # The existing keys survive.
        self.assertEqual(r.data['invoiced'], '1400.00')
        self.assertIn('profit', r.data)

    def test_business_financials_rollup_spans_all_contacts(self):
        r = self.client.get(f'/api/businesses/{self.business.business_id}/financials/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['open_jobs'], 2)
        self.assertEqual(r.data['outstanding'], '1050.00')
        self.assertEqual(r.data['first_job_date'], self.d_first)
        self.assertEqual(r.data['last_job_start'], self.d_last)
        self.assertEqual(r.data['invoiced'], '1700.00')

    def test_financials_with_no_jobs_are_null_and_zero(self):
        lonely = Contact.objects.create(
            first_name='No', last_name='Jobs', email='nojobs@harbor.test')
        r = self.client.get(f'/api/contacts/{lonely.contact_id}/financials/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['open_jobs'], 0)
        self.assertEqual(r.data['outstanding'], '0.00')
        self.assertIsNone(r.data['first_job_date'])
        self.assertIsNone(r.data['last_job_start'])

    def test_job_summary_rows_carry_contact_dates_and_estimate(self):
        r = self.client.get(f'/api/businesses/{self.business.business_id}/')
        self.assertEqual(r.status_code, 200)
        rows = {j['job_number']: j for j in r.data['jobs']}
        row = rows['JOB-CF-1']
        self.assertEqual(row['contact'], self.contact.contact_id)
        self.assertEqual(row['contact_name'], 'Dana Whitfield')
        self.assertIsNotNone(row['start_date'])
        self.assertIsNotNone(row['created_date'])
        self.assertEqual(row['estimated_amount'], '0.00')
        self.assertIsNone(rows['JOB-CF-3']['start_date'])

        r = self.client.get(f'/api/contacts/{self.contact.contact_id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual({j['job_number'] for j in r.data['jobs']}, {'JOB-CF-1', 'JOB-CF-2'})
        self.assertIn('estimated_amount', r.data['jobs'][0])

    def test_business_contacts_carry_primary_phone(self):
        r = self.client.get(f'/api/businesses/{self.business.business_id}/')
        by_id = {c['contact_id']: c for c in r.data['contacts']}
        self.assertEqual(by_id[self.sibling.contact_id]['phone'], '555-0171')
        self.assertEqual(by_id[self.contact.contact_id]['phone'], '555-0147')

    def test_business_payload_carries_terms_name(self):
        r = self.client.get(f'/api/businesses/{self.business.business_id}/')
        self.assertIsNone(r.data['terms_name'])
        terms = PaymentTerms.objects.create(name='Net 30', days=30)
        self.business.terms = terms
        self.business.save()
        r = self.client.get(f'/api/businesses/{self.business.business_id}/')
        self.assertEqual(r.data['terms_name'], 'Net 30')
        self.assertEqual(r.data['terms'], terms.term_id)


class CustomerFinancialsWindowTest(BaseTestCase):
    """Rolling window over closed jobs for compute_customer_financials."""

    def setUp(self):
        super().setUp()
        from django.utils import timezone
        from apps.core.models import Configuration
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.contact = Contact.objects.create(
            first_name='Win', last_name='Dow', email='win@dow.test')
        self.fixed = timezone.now()
        Configuration.objects.update_or_create(
            key='customer_financials_window_months', defaults={'value': '12'})
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '50'})
        self.n = 0

    def _job(self, status, completed=None, **kw):
        from apps.jobs.models import Job
        self.n += 1
        return Job.objects.create(
            job_number=f'JOB-WIN-{self.n}', name='w', status=status,
            contact=self.contact, completed_date=completed, **kw)

    def _invoice(self, job, amount, status=None):
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.invoicing.models import Invoice, InvoiceLineItem
        ac = AccountingCategory.objects.create(
            code=f'WIN{self.n}{Invoice.objects.count()}', name='win')
        inv = Invoice.objects.create(
            job=job, invoice_number=f'WIN-{Invoice.objects.count() + 1}',
            status=status or Invoice.STATUS_PAID)
        InvoiceLineItem.objects.create(
            invoice=inv, line_number=1, qty=1, price=Decimal(str(amount)),
            accounting_category=ac, description='x')
        return inv

    def _roll(self):
        from apps.jobs.models import Job
        from apps.jobs.financials import compute_customer_financials
        return compute_customer_financials(
            Job.objects.filter(contact=self.contact), now=self.fixed)

    def _ago(self, months):
        from dateutil.relativedelta import relativedelta
        return self.fixed - relativedelta(months=months)

    def test_open_job_always_in_window(self):
        from apps.jobs.models import Job
        job = self._job(Job.STATUS_APPROVED, start_date=self._ago(30))
        self._invoice(job, 100)
        self.assertEqual(str(self._roll()['invoiced']), '100.00')

    def test_closed_job_inside_window_in_and_outside_out(self):
        from apps.jobs.models import Job
        self._invoice(self._job(Job.STATUS_COMPLETED, self._ago(11)), 100)
        self._invoice(self._job(Job.STATUS_COMPLETED, self._ago(13)), 1000)
        self.assertEqual(str(self._roll()['invoiced']), '100.00')

    def test_closed_job_on_the_cutoff_is_in(self):
        from apps.jobs.models import Job
        self._invoice(self._job(Job.STATUS_COMPLETED, self._ago(12)), 100)
        self.assertEqual(str(self._roll()['invoiced']), '100.00')

    def test_closed_job_with_null_completed_date_is_out(self):
        from apps.jobs.models import Job
        job = self._job(Job.STATUS_ARCHIVED, None)
        self._invoice(job, 100)
        r = self._roll()
        self.assertEqual(str(r['invoiced']), '0.00')
        self.assertFalse(r['includes_archived'])

    def test_window_config_override_and_default(self):
        from apps.core.models import Configuration
        from apps.jobs.models import Job
        self._invoice(self._job(Job.STATUS_COMPLETED, self._ago(4)), 100)
        Configuration.objects.filter(
            key='customer_financials_window_months').update(value='3')
        r = self._roll()
        self.assertEqual(r['window_months'], 3)
        self.assertEqual(str(r['invoiced']), '0.00')
        Configuration.objects.filter(
            key='customer_financials_window_months').delete()
        r = self._roll()
        self.assertEqual(r['window_months'], 12)
        self.assertEqual(str(r['invoiced']), '100.00')
        Configuration.objects.create(
            key='customer_financials_window_months', value='abc')
        self.assertEqual(self._roll()['window_months'], 12)

    def _archived_with_work(self, completed):
        from decimal import Decimal
        from apps.jobs.models import Job, Task
        job = self._job(Job.STATUS_ARCHIVED, completed)
        self._invoice(job, 1000)
        Task.objects.create(
            job=job, name='h', status=Task.STATUS_COMPLETE,
            qty_source=Task.QTY_ENTERED, unit_label='hour',
            actual_qty=Decimal('10'))
        return job

    def test_archived_in_window_counts_toward_invoiced_and_profit_and_sets_flag(self):
        self._archived_with_work(self._ago(2))
        r = self._roll()
        self.assertEqual(str(r['invoiced']), '1000.00')
        self.assertEqual(str(r['profit']), '500.00')
        self.assertIs(r['includes_archived'], True)

    def test_archived_outside_window_is_excluded(self):
        self._archived_with_work(self._ago(13))
        r = self._roll()
        self.assertEqual(str(r['invoiced']), '0.00')
        self.assertEqual(str(r['profit']), '0.00')
        self.assertIs(r['includes_archived'], False)

    def test_open_jobs_and_outstanding_ignore_the_window(self):
        from apps.invoicing.models import Invoice
        from apps.jobs.models import Job
        job = self._job(Job.STATUS_APPROVED, start_date=self._ago(14))
        self._invoice(job, 300, status=Invoice.STATUS_OPEN)
        r = self._roll()
        self.assertEqual(r['open_jobs'], 1)
        self.assertEqual(str(r['outstanding']), '300.00')

    def test_financials_endpoint_exposes_window_and_flag(self):
        r = self.client.get(f'/api/contacts/{self.contact.contact_id}/financials/')
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data['window_months'], int)
        self.assertIsInstance(r.data['includes_archived'], bool)
