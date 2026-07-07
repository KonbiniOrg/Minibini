"""
Tests for decoupling Task from ServiceItem.

NOTE: As of B6, Task/ServiceItem no longer have direct
accounting_category fields — the effective category is derived from
the linked RateScheme. The original AC-on-task tests have been
removed. The HTML-view subclasses (TaskDetailAccountingCategoryTests)
are also gone with the rest of the HTML test suite.

This module is kept as a placeholder so the test runner can still
discover it; real coverage of accounting-category resolution lives
in the rate-scheme and effective_accounting_category tests.
"""
from django.test import TestCase


class PlaceholderTest(TestCase):
    def test_placeholder(self):
        # Intentionally trivial: see module docstring.
        self.assertTrue(True)
