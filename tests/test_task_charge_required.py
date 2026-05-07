from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import BaseTestCase


class TaskCreationProducesChargeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import TaskTemplate
        from apps.contacts.models import Business, Contact
        self.ac = AccountingCategory.objects.create(code='X-tcr', name='X-tcr')
        self.scheme = RateScheme.objects.create(
            name='S-tcr', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.template = TaskTemplate.objects.create(
            template_name='T-tcr', rate_scheme=self.scheme,
            default_billable_qty=Decimal('1'),
        )
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-tcr@l.test',
        )
        biz = Business.objects.create(
            business_name='B-tcr', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='J-tcr', contact=contact)

    def test_create_from_template_sets_rate_scheme_on_task(self):
        from apps.jobs.services import TaskService
        task = TaskService.create_from_template(self.template, self.job)
        self.assertEqual(task.rate_scheme, self.scheme)

    def test_create_direct_without_scheme_raises(self):
        from apps.jobs.services import TaskService
        with self.assertRaises(ValidationError):
            TaskService.create_direct(self.job, name='no scheme')

    def test_create_direct_with_scheme_sets_rate_scheme_on_task(self):
        from apps.jobs.services import TaskService
        task = TaskService.create_direct(
            self.job, name='ok', rate_scheme_id=self.scheme.pk,
        )
        self.assertEqual(task.rate_scheme_id, self.scheme.pk)

    def test_template_with_superseded_scheme_raises(self):
        from apps.jobs.services import TaskService
        from apps.core.services import SchemeSupersededError
        # Supersede the scheme so the template now points at a superseded one
        self.scheme.supersede(name='S-tcr v2')
        with self.assertRaises(SchemeSupersededError):
            TaskService.create_from_template(self.template, self.job)


class TaskCleanNoLongerRequiresChargeTest(BaseTestCase):
    """B4 removed the hasattr(self, 'charge') guard from Task.clean().
    Tasks can now exist without a TaskCharge. rate_scheme will be required
    (NOT NULL) in B8.
    """
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.contacts.models import Business, Contact
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-tcrc@l.test',
        )
        biz = Business.objects.create(
            business_name='B-tcrc', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='J-tcrc', contact=contact)

    def test_task_full_clean_succeeds_without_charge(self):
        from apps.jobs.models import Task
        t = Task.objects.create(job=self.job, name='no charge')
        # Should not raise — charge guard removed in B4
        t.full_clean()
