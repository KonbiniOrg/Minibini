from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.estimates.models import Estimate, EstimateLineItem


class EstimateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_estimates(self):
        response = self.client.get('/api/estimates/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_estimate(self):
        estimate = Estimate.objects.first()
        response = self.client.get(f'/api/estimates/{estimate.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('line_items', response.data)

    def test_update_estimate(self):
        estimate = Estimate.objects.filter(status='draft').first()
        if estimate:
            response = self.client.patch(f'/api/estimates/{estimate.pk}/', {
                'status': 'draft',
            }, format='json')
            self.assertEqual(response.status_code, 200)

    def test_add_line_item(self):
        estimate = Estimate.objects.first()
        response = self.client.post(f'/api/estimates/{estimate.pk}/line-items/', {
            'qty': '2.00',
            'units': 'ea',
            'description': 'API test item',
            'price': '100.00',
        }, format='json')
        self.assertIn(response.status_code, [200, 201])

    def test_list_line_items(self):
        estimate = Estimate.objects.first()
        response = self.client.get(f'/api/estimates/{estimate.pk}/line-items/')
        self.assertEqual(response.status_code, 200)

    def test_delete_line_item(self):
        line_item = EstimateLineItem.objects.first()
        if line_item:
            estimate = line_item.estimate
            response = self.client.delete(
                f'/api/estimates/{estimate.pk}/line-items/{line_item.pk}/'
            )
            self.assertEqual(response.status_code, 204)
