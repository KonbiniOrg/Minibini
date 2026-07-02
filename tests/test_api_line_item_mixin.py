from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class LineItemMixinTest(BaseTestCase):
    """Test LineItemMixin is importable and has expected attributes."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_mixin_importable(self):
        """LineItemMixin should be importable."""
        from apps.api.mixins import LineItemMixin
        self.assertTrue(hasattr(LineItemMixin, 'line_items'))
