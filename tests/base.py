from django.test import TestCase


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