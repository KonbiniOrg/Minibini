from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import RateScheme, PlanTask, Job
from apps.jobs.services import JobService
from apps.estimates.models import EstWorksheet
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact
from tests.base import BaseTestCase


class CopyFromWorksheetChargeTest(TestCase):

    def setUp(self):
        self.category = AccountingCategory.objects.create(
            code='LAB', name='Labor', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='test@test.com',
        )
        self.job = Job.objects.create(
            name='Test Job', job_number='TEST-001', status='approved',
            contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='CNC Router Copy Test',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[
                {'key': 'messy', 'label': 'Messy', 'percent': 10},
            ],
            accounting_category=self.category,
        )

    def test_copy_sets_task_billing_fields_from_plan_task(self):
        plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='CNC cut panels',
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            est_qty=Decimal('30.00'),
        )

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        task = self.job.tasks.get(name='CNC cut panels')
        self.assertEqual(task.rate_scheme, self.scheme)
        self.assertEqual(task.active_modifiers, ['messy'])
        self.assertEqual(task.est_qty, Decimal('30.00'))


class GenerateTaskEstWorksheetBranchTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import ServiceItem, EstWorksheet
        from apps.contacts.models import Business, Contact
        ac = AccountingCategory.objects.create(code='X', name='X')
        self.scheme = RateScheme.objects.create(
            name='S-gtw', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        self.template = ServiceItem.objects.create(
            template_name='T-gtw', rate_scheme=self.scheme,
            default_active_modifiers=['m1'],
            default_billable_qty=Decimal('5'),
        )
        # NOTE: actual schema requires Business.business_name + default_contact FK,
        # and Contact.email. Build pair: Contact first, then Business with
        # default_contact, then attach business back to contact and save.
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f@l.test',
        )
        biz = Business.objects.create(
            business_name='B-gtw', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J-gtw', contact=contact)
        self.ws = EstWorksheet.objects.create(job=job)

    def test_generate_task_for_worksheet_propagates_scheme(self):
        pt = self.template.generate_task(self.ws, est_qty=Decimal('5'))
        self.assertEqual(pt.rate_scheme, self.scheme)
        self.assertEqual(pt.active_modifiers, ['m1'])
        self.assertEqual(pt.est_qty, Decimal('5'))


class EffectiveACPropertyTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme
        self.scheme_ac = AccountingCategory.objects.create(code='S-eac', name='Scheme AC')
        self.scheme = RateScheme.objects.create(
            name='S-eac', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.scheme_ac,
        )

    def _make_job(self):
        from apps.contacts.models import Business, Contact
        from apps.jobs.models import Job
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-eac@l.test',
        )
        biz = Business.objects.create(
            business_name='B-eac', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        return Job.objects.create(job_number='J-eac', contact=contact)

    def test_planTask_effective_ac_comes_from_scheme(self):
        from apps.jobs.models import PlanTask
        from apps.estimates.models import EstWorksheet
        job = self._make_job()
        ws = EstWorksheet.objects.create(job=job)
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='t',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
        )
        self.assertEqual(pt.effective_accounting_category, self.scheme_ac)

    def test_task_effective_ac_comes_from_rate_scheme(self):
        from apps.jobs.models import Task
        job = self._make_job()
        t = Task.objects.create(job=job, name='t', rate_scheme=self.scheme)
        self.assertEqual(t.effective_accounting_category, self.scheme_ac)

    def test_taskTemplate_effective_ac_comes_from_scheme(self):
        from apps.estimates.models import ServiceItem
        tt = ServiceItem.objects.create(
            template_name='tt-eac', rate_scheme=self.scheme,
            default_billable_qty=Decimal('1'),
        )
        self.assertEqual(tt.effective_accounting_category, self.scheme_ac)


class AddTaskManualRequiresSchemeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Business, Contact
        self.ac = AccountingCategory.objects.create(code='X-atm', name='X-atm')
        self.scheme = RateScheme.objects.create(
            name='S-atm', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-atm@l.test',
        )
        biz = Business.objects.create(
            business_name='B-atm', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J-atm', contact=contact)
        self.ws = EstWorksheet.objects.create(job=job)

    def test_add_task_manual_without_scheme_raises(self):
        from apps.estimates.services import WorksheetService
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            WorksheetService.add_task_manual(
                self.ws.pk, name='no scheme',
                est_qty=Decimal('1'),
            )

    def test_add_task_manual_with_scheme_succeeds(self):
        from apps.estimates.services import WorksheetService
        pt = WorksheetService.add_task_manual(
            self.ws.pk, name='ok',
            rate_scheme_id=self.scheme.pk,
            est_qty=Decimal('1'),
        )
        self.assertEqual(pt.rate_scheme_id, self.scheme.pk)


class PlanTaskSerializerNoACTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from apps.jobs.models import RateScheme
        self.user = User.objects.create_user('u-pts', 'u-pts@x.test', 'pw')
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='X-pts', name='X-pts')
        self.scheme = RateScheme.objects.create(
            name='S-pts', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )

    def test_plan_task_detail_omits_accounting_category(self):
        from apps.jobs.models import Job, PlanTask
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Business, Contact
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-pts@l.test',
        )
        biz = Business.objects.create(
            business_name='B-pts', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J-pts', contact=contact)
        ws = EstWorksheet.objects.create(job=job)
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='t',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
        )
        resp = self.client.get(f'/api/plan-tasks/{pt.pk}/')
        body = resp.json()
        self.assertNotIn('accounting_category', body)
        self.assertIn('rate_scheme', body)
