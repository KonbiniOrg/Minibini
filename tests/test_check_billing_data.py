import unittest
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from tests.base import BaseTestCase


class CheckBillingDataTest(BaseTestCase):
    fixtures = []

    def test_clean_db_reports_all_clear(self):
        out = StringIO()
        call_command('check_billing_data', stdout=out)
        text = out.getvalue()
        self.assertIn('All clear', text)

    @unittest.skip(
        "Phase B (migrations 0028/0029) made PlanTask.rate_scheme + est_qty "
        "NOT NULL at both the model (full_clean) and DB layers, so the orphan "
        "row this test relied on is impossible to create. The check_billing_data "
        "management command's PlanTask-without-scheme branch is now dead code "
        "kept for safety."
    )
    def test_reports_planTask_without_scheme(self):
        pass
