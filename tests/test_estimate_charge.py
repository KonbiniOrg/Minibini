from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import RateScheme, Job
from apps.jobs.services import JobService
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact
from tests.base import BaseTestCase


class GenerateTaskForJobChargeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import ServiceItem
        from apps.contacts.models import Business, Contact
        ac = AccountingCategory.objects.create(code='X', name='X')
        self.scheme = RateScheme.objects.create(
            name='S-gtw', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
            modifiers=[{'key': 'm1', 'label': 'Modifier 1', 'percent': 10}],
        )
        self.template = ServiceItem.objects.create(
            template_name='T-gtw', rate_scheme=self.scheme,
            default_active_modifiers=['m1'],
        )
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f@l.test',
        )
        biz = Business.objects.create(
            business_name='B-gtw', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='J-gtw', contact=contact)

    def test_generate_task_for_job_propagates_scheme(self):
        task = self.template.generate_task(self.job, est_qty=Decimal('5'))
        self.assertEqual(task.source_scheme, self.scheme)
        # active_modifiers is a snapshot of {key,label,percent} dicts
        # (task-owned-money Phase 1), not the raw key list passed in.
        self.assertEqual(
            task.active_modifiers,
            [{'key': 'm1', 'label': 'Modifier 1', 'percent': 10}],
        )
        self.assertEqual(task.est_qty, Decimal('5'))


class EffectiveACPropertyTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme
        self.scheme_ac = AccountingCategory.objects.create(code='S-eac', name='Scheme AC')
        self.scheme = RateScheme.objects.create(
            name='S-eac', algorithm='entered_qty', rate=Decimal('1'),
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

    def test_task_effective_ac_comes_from_rate_scheme(self):
        from apps.jobs.models import Task
        job = self._make_job()
        t = Task(job=job, name='t')
        t.stamp_from_scheme(self.scheme)
        t.save()
        self.assertEqual(t.effective_accounting_category, self.scheme_ac)

    def test_taskTemplate_effective_ac_comes_from_scheme(self):
        from apps.estimates.models import ServiceItem
        tt = ServiceItem.objects.create(
            template_name='tt-eac', rate_scheme=self.scheme,
        )
        self.assertEqual(tt.effective_accounting_category, self.scheme_ac)


class TaskCreateRequiresSchemeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.contacts.models import Business, Contact
        self.ac = AccountingCategory.objects.create(code='X-atm', name='X-atm')
        self.scheme = RateScheme.objects.create(
            name='S-atm', algorithm='entered_qty', rate=Decimal('1'),
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
        self.job = Job.objects.create(job_number='J-atm', contact=contact)

    def test_create_direct_without_scheme_raises(self):
        from apps.jobs.services import TaskService
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                job=self.job, name='no scheme',
                est_qty=Decimal('1'),
            )

    def test_create_direct_with_scheme_succeeds(self):
        from apps.jobs.services import TaskService
        task = TaskService.create_direct(
            job=self.job, name='ok',
            rate_scheme_id=self.scheme.pk,
            est_qty=Decimal('1'),
        )
        self.assertEqual(task.source_scheme_id, self.scheme.pk)
