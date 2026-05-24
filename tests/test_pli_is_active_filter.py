from decimal import Decimal
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory, User
from apps.inventory.models import PriceListItem


class PriceListItemIsActiveFilterTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = AccountingCategory.objects.create(code='C', name='Cat')
        cls.active = PriceListItem.objects.create(
            code='ACT-1', description='active item', accounting_category=cls.cat,
            is_active=True,
        )
        cls.inactive = PriceListItem.objects.create(
            code='INACT-1', description='retired item', accounting_category=cls.cat,
            is_active=False,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _codes(self, response):
        return sorted(item['code'] for item in response.json()['results'])

    def test_no_filter_returns_all(self):
        resp = self.client.get('/api/price-list-items/')
        self.assertEqual(self._codes(resp), ['ACT-1', 'INACT-1'])

    def test_is_active_true_excludes_deactivated(self):
        resp = self.client.get('/api/price-list-items/?is_active=true')
        self.assertEqual(self._codes(resp), ['ACT-1'])

    def test_is_active_false_returns_only_deactivated(self):
        resp = self.client.get('/api/price-list-items/?is_active=false')
        self.assertEqual(self._codes(resp), ['INACT-1'])
