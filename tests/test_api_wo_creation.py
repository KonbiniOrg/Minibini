from django.test import TestCase
from rest_framework.test import APIClient
from apps.core.models import User
from apps.contacts.models import Contact
from apps.jobs.models import Job, WorkOrder, Task, PlanTask, PlanBundle
from apps.estimates.models import (
    Estimate, EstWorksheet, WorkOrderTemplate, TaskTemplate,
    TemplateTaskAssociation,
)
from apps.inventory.models import PlanMaterial


def make_admin():
    user = User.objects.create_user(username='admin_wo', password='pass')
    from django.contrib.auth.models import Permission
    perm = Permission.objects.get(codename='can_manage_jobs')
    user.user_permissions.add(perm)
    return user


class CreateFromTemplateTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_admin()
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='Test', last_name='Contact')
        self.job = Job.objects.create(job_number='WO-T-001', name='Template Job', contact=self.contact)
        self.template = WorkOrderTemplate.objects.create(
            template_name='Kitchen Install', is_active=True,
        )
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.create(name='Labor')
        self.task_template = TaskTemplate.objects.create(
            template_name='Countertop', is_active=True,
            units='each', rate=100,
            accounting_category=cat,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.template,
            task_template=self.task_template,
            est_qty=2,
            sort_order=1,
        )

    def test_create_from_template_success(self):
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('work_order_id', response.data)
        wo = WorkOrder.objects.get(pk=response.data['work_order_id'])
        self.assertEqual(wo.job, self.job)
        self.assertEqual(wo.tasks.count(), 1)
        self.assertEqual(wo.tasks.first().name, 'Countertop')

    def test_create_from_template_missing_template(self):
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_create_from_template_inactive_template(self):
        self.template.is_active = False
        self.template.save()
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='worker_wo', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class CreateFromEstimateTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_admin()
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='Test', last_name='EstContact')
        self.job = Job.objects.create(job_number='WO-E-001', name='Estimate Job', contact=self.contact)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-001',
            status=Estimate.STATUS_ACCEPTED,
        )

    def test_create_from_accepted_estimate(self):
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('work_order_id', response.data)
        wo = WorkOrder.objects.get(pk=response.data['work_order_id'])
        self.assertEqual(wo.job, self.job)

    def test_create_from_open_estimate(self):
        open_estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-002',
            status=Estimate.STATUS_OPEN,
        )
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': open_estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_rejects_draft_estimate(self):
        draft_estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-003',
            status=Estimate.STATUS_DRAFT,
        )
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': draft_estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_estimate(self):
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='worker_est', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)
