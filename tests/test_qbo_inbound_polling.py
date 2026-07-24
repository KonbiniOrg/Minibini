from unittest.mock import patch
from django.test import TestCase
from apps.qbo.services import QBOInboundPollingService


class InboundPollingTest(TestCase):
    @patch('apps.qbo.services.QBOService.get_client', return_value=None)
    def test_orchestrator_reports_invoice_branch_without_connection(self, _m):
        stats = QBOInboundPollingService.poll_all()
        self.assertIn('invoices', stats)
        self.assertNotIn('bills', stats)  # bill polling retired with the Bill domain
