from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class LineItemMixinTest(BaseTestCase):
    """Test LineItemMixin and TaskBundleMixin are importable and have expected attributes."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_mixin_importable(self):
        """LineItemMixin and TaskBundleMixin should be importable."""
        from apps.api.mixins import LineItemMixin, TaskBundleMixin
        self.assertTrue(hasattr(LineItemMixin, 'line_items'))
        self.assertTrue(hasattr(TaskBundleMixin, 'tasks'))
