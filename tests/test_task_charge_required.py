from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme


class TaskCreationProducesChargeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import ServiceItem
        from apps.contacts.models import Business, Contact
        self.ac = AccountingCategory.objects.create(code='X-tcr', name='X-tcr')
        self.scheme = RateScheme.objects.create(
            name='S-tcr', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.template = ServiceItem.objects.create(
            template_name='T-tcr', rate_scheme=self.scheme,
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
        self.assertEqual(task.source_scheme, self.scheme)

    def test_create_direct_without_scheme_raises(self):
        from apps.jobs.services import TaskService
        with self.assertRaises(ValidationError):
            TaskService.create_direct(self.job, name='no scheme')

    def test_create_direct_with_scheme_sets_rate_scheme_on_task(self):
        from apps.jobs.services import TaskService
        task = TaskService.create_direct(
            self.job, name='ok', rate_scheme_id=self.scheme.pk,
        )
        self.assertEqual(task.source_scheme_id, self.scheme.pk)

    def test_create_direct_with_inactive_scheme_raises_by_default(self):
        from apps.jobs.models import SchemeInactiveError
        from apps.jobs.services import TaskService
        RateScheme.objects.filter(pk=self.scheme.pk).update(is_active=False)
        with self.assertRaises(SchemeInactiveError):
            TaskService.create_direct(
                self.job, name='x', rate_scheme_id=self.scheme.pk,
            )

    def test_create_direct_allow_inactive_scheme_bypasses_check(self):
        from apps.jobs.services import TaskService
        RateScheme.objects.filter(pk=self.scheme.pk).update(is_active=False)
        task = TaskService.create_direct(
            self.job, name='clone', rate_scheme_id=self.scheme.pk,
            allow_inactive_scheme=True,
        )
        self.assertEqual(task.source_scheme_id, self.scheme.pk)


class TaskCleanNoLongerRequiresChargeTest(BaseTestCase):
    """B4 removed the hasattr(self, 'charge') guard from Task.clean().
    B8 makes rate_scheme NOT NULL at the DB level — Tasks always have it.
    """
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import Job, RateScheme
        from apps.contacts.models import Business, Contact
        ac = AccountingCategory.objects.create(code='B8-tcrc', name='B8-tcrc')
        self.scheme = RateScheme.objects.create(
            name='S-tcrc', algorithm='entered_qty', rate=1,
            unit_label='ea', accounting_category=ac,
        )
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
        """B4 removed charge guard; B8 requires rate_scheme. Task stamped from a
        scheme passes clean."""
        from apps.jobs.models import Task
        t = Task(job=self.job, name='with scheme')
        t.stamp_from_scheme(self.scheme)
        t.save()
        # Should not raise — charge guard removed in B4, rate_scheme required (B8)
        t.full_clean()
