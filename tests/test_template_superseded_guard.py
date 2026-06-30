from decimal import Decimal
from tests.base import BaseTestCase


class TemplateSupersededGuardTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import ServiceItem, EstWorksheet
        from apps.contacts.models import Business, Contact
        self.ac = AccountingCategory.objects.create(code='X-tsg', name='X-tsg')
        self.old_scheme = RateScheme.objects.create(
            name='O-tsg', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.template = ServiceItem.objects.create(
            template_name='T-tsg', rate_scheme=self.old_scheme,
        )
        self.new_scheme = self.old_scheme.supersede(name='N-tsg')
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-tsg@l.test',
        )
        biz = Business.objects.create(
            business_name='B-tsg', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='J-tsg', contact=contact)
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_generate_task_for_task_branch_raises(self):
        from apps.core.services import SchemeSupersededError
        with self.assertRaises(SchemeSupersededError) as cm:
            self.template.generate_task(self.job, est_qty=Decimal('1'))
        self.assertIn('superseded', str(cm.exception).lower())


class TemplateSupersededAPITest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        from django.contrib.auth.models import Permission
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import ServiceItem
        from apps.contacts.models import Business, Contact
        self.user = User.objects.create_user('admin-tsg', 'admin-tsg@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='X-tsga', name='X-tsga')
        self.old_scheme = RateScheme.objects.create(
            name='O-tsga', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.template = ServiceItem.objects.create(
            template_name='T-tsga', rate_scheme=self.old_scheme,
        )
        self.new_scheme = self.old_scheme.supersede(name='N-tsga')
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-tsga@l.test',
        )
        biz = Business.objects.create(
            business_name='B-tsga', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='J-tsga', contact=contact)

    def test_add_from_template_with_superseded_scheme_returns_409(self):
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'service_item_id': self.template.pk, 'est_qty': '1'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)
        self.assertIn('superseded', resp.json().get('detail', '').lower())
