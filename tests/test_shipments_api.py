from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import ShipmentService
from apps.estimates.models import Estimate
from apps.jobs.models import Job


User = get_user_model()


def _job_with_accept():
    job = Job.objects.first()
    Estimate.objects.filter(job=job).delete()
    Deliverable.objects.filter(job=job).delete()
    Shipment.objects.filter(job=job).delete()
    Estimate.objects.create(
        job=job, estimate_number='EST-SH-1', version=1, status=Estimate.STATUS_ACCEPTED,
    )
    return job


def _plain_user():
    user = User.objects.filter(is_active=True).first()
    if not user:
        user = User.objects.create_user(username='u', password='x', email='u@x.com')
    return user


class ShipmentCreateAPITests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_plain_user())

    def test_create_requires_accepted_estimate(self):
        job = Job.objects.first()
        Estimate.objects.filter(job=job).delete()
        r = self.client.post(f'/api/jobs/{job.pk}/shipments/', {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_create_succeeds_when_d_list_locked(self):
        job = _job_with_accept()
        r = self.client.post(f'/api/jobs/{job.pk}/shipments/', {}, format='json')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body['status'], 'prepared')
        self.assertEqual(body['sequence'], 1)


class ShipmentListAndDetailAPITests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_plain_user())
        self.job = _job_with_accept()
        self.s = ShipmentService.create(job_id=self.job.pk)

    def test_list_filterable_by_job(self):
        r = self.client.get(f'/api/shipments/?job={self.job.pk}')
        self.assertEqual(r.status_code, 200)
        ids = [item['id'] for item in r.json()['results']]
        self.assertIn(self.s.pk, ids)

    def test_patch_notes(self):
        r = self.client.patch(
            f'/api/shipments/{self.s.pk}/',
            {'notes': 'Wrapped in newspaper'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.s.refresh_from_db()
        self.assertEqual(self.s.notes, 'Wrapped in newspaper')

    def test_delete_prepared_empty(self):
        r = self.client.delete(f'/api/shipments/{self.s.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0], 'application/json')
        self.assertFalse(Shipment.objects.filter(pk=self.s.pk).exists())

    def test_pick_up_action(self):
        r = self.client.post(f'/api/shipments/{self.s.pk}/pick-up/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, 'picked_up')
        self.assertIsNotNone(self.s.picked_up_date)


class ShipmentItemAPITests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_plain_user())
        self.job = _job_with_accept()
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.s = ShipmentService.create(job_id=self.job.pk)

    def test_add_item(self):
        r = self.client.post(
            f'/api/shipments/{self.s.pk}/items/',
            {'deliverable': self.d.pk, 'qty': '10'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)

    def test_add_item_exceeding_remaining_rejected(self):
        r = self.client.post(
            f'/api/shipments/{self.s.pk}/items/',
            {'deliverable': self.d.pk, 'qty': '20'},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_patch_item(self):
        item = ShipmentService.add_item(shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'))
        r = self.client.patch(
            f'/api/shipments/{self.s.pk}/items/{item.pk}/',
            {'qty': '7'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.qty, Decimal('7'))

    def test_delete_item(self):
        item = ShipmentService.add_item(shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'))
        r = self.client.delete(f'/api/shipments/{self.s.pk}/items/{item.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ShipmentItem.objects.filter(pk=item.pk).exists())


class PackingListAPITests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_plain_user())
        self.job = _job_with_accept()
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.s = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('10'))

    def test_packing_list_endpoint(self):
        r = self.client.get(f'/api/shipments/{self.s.pk}/packing-list/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['shipment']['sequence'], 1)
        self.assertEqual(body['job']['id'], self.job.pk)
        self.assertEqual(len(body['rows']), 1)
        self.assertEqual(body['rows'][0]['qty_this_shipment'], '10.00')
