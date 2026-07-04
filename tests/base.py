from django.test import TestCase


def grant_atoms(user, *codenames):
    """Grant permission atoms (e.g. 'can_manage_time') to a test user and
    return the user refetched so the permission cache is fresh. Use this
    instead of the is_superuser=True shortcut — authorization is atoms-only."""
    from django.contrib.auth.models import Permission
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(
            codename=codename, content_type__app_label='core'))
    return type(user).objects.get(pk=user.pk)


class BaseTestCase(TestCase):
    """
    Base test case class that loads fixture data for all tests.
    This provides a consistent set of test data across all test classes.
    """
    fixtures = ['unit_test_data.json']
    
    def setUp(self):
        """
        Set up method that runs before each test.
        Fixture data is automatically loaded before this method runs.
        """
        super().setUp()
        
    @classmethod
    def setUpTestData(cls):
        """
        Set up class-level test data that persists across test methods.
        This is more efficient than setUp() for read-only data.
        """
        super().setUpTestData()


class FixtureTestCase(BaseTestCase):
    """
    Test case specifically for testing with fixture data.
    Inherits from BaseTestCase to get all fixture data loaded.
    """
    pass