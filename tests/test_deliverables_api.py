from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable
from apps.estimates.models import Estimate
from apps.jobs.models import Job


User = get_user_model()


def _job_clean():
    job = Job.objects.first()
    Estimate.objects.filter(job=job).delete()
    Deliverable.objects.filter(job=job).delete()
    return job


def _manager():
    user = User.objects.filter(
        user_permissions__codename='can_manage_jobs', is_active=True,
    ).first()
    if user:
        return user
    perm = Permission.objects.get(codename='can_manage_jobs')
    user = User.objects.create_user(username='mgr', password='x', email='m@x.com')
    user.user_permissions.add(perm)
    return user


def _plain_user():
    # Exclude superusers (which bypass every atom check) AND users who hold
    # the can_manage_jobs perm. Fall back to creating a fresh user.
    user = User.objects.filter(is_active=True, is_superuser=False).exclude(
        user_permissions__codename='can_manage_jobs',
    ).first()
    if user:
        return user
    user = User.objects.create_user(username='plain', password='x', email='p@x.com')
    return user


class DeliverableAPIPermissionTests(FixtureTestCase):

    def test_list_requires_auth(self):
        client = APIClient()
        job = _job_clean()
        r = client.get(f'/api/jobs/{job.pk}/deliverables/')
        self.assertIn(r.status_code, (401, 403))

    def test_list_works_with_any_authenticated_user(self):
        client = APIClient()
        client.force_authenticate(user=_plain_user())
        job = _job_clean()
        r = client.get(f'/api/jobs/{job.pk}/deliverables/')
        self.assertEqual(r.status_code, 200)

    def test_create_requires_can_manage_jobs(self):
        client = APIClient()
        client.force_authenticate(user=_plain_user())
        job = _job_clean()
        r = client.post(
            f'/api/jobs/{job.pk}/deliverables/',
            {'description': 'Stool', 'qty_ordered': '15', 'units': 'ea'},
            format='json',
        )
        self.assertEqual(r.status_code, 403)

    def test_create_allowed_for_manager(self):
        client = APIClient()
        client.force_authenticate(user=_manager())
        job = _job_clean()
        r = client.post(
            f'/api/jobs/{job.pk}/deliverables/',
            {'description': 'Stool', 'qty_ordered': '15', 'units': 'ea'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)


class DeliverableAPICRUDTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = _job_clean()
        self.client = APIClient()
        self.client.force_authenticate(user=_manager())

    def test_create_returns_serializer_fields(self):
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/',
            {'description': 'Stool', 'qty_ordered': '15', 'units': 'ea'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body['description'], 'Stool')
        self.assertEqual(body['qty_remaining'], '15.00')

    def test_create_rejected_when_estimate_open(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Q-1', version=1,
            status=Estimate.STATUS_OPEN,
        )
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/',
            {'description': 'Stool', 'qty_ordered': '15', 'units': 'ea'},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_patch_updates_fields(self):
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        r = self.client.patch(
            f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/',
            {'description': 'Walnut stool'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        d.refresh_from_db()
        self.assertEqual(d.description, 'Walnut stool')

    def test_delete_returns_200_json(self):
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        r = self.client.delete(f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0], 'application/json')
        self.assertIn('message', r.json())

    def test_reorder_endpoint(self):
        a = Deliverable.objects.create(job=self.job, description='A', qty_ordered=Decimal('1'), units='ea', sort_order=10)
        b = Deliverable.objects.create(job=self.job, description='B', qty_ordered=Decimal('1'), units='ea', sort_order=20)
        c = Deliverable.objects.create(job=self.job, description='C', qty_ordered=Decimal('1'), units='ea', sort_order=30)

        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/reorder/',
            {'ordered_ids': [c.pk, a.pk, b.pk]},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        ids = list(
            Deliverable.objects.filter(job=self.job).order_by('sort_order').values_list('pk', flat=True)
        )
        self.assertEqual(ids, [c.pk, a.pk, b.pk])

    def test_editability_endpoint(self):
        r = self.client.get(f'/api/jobs/{self.job.pk}/deliverables/editability/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['editable'])
        self.assertIsNone(body['reason'])

        Estimate.objects.create(
            job=self.job, estimate_number='EST-E-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        r = self.client.get(f'/api/jobs/{self.job.pk}/deliverables/editability/')
        body = r.json()
        self.assertFalse(body['editable'])
        self.assertEqual(body['reason'], 'estimate_accepted')
