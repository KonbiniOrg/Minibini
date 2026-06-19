from unittest.mock import patch
from django.test import TestCase
from apps.qbo.services import QBOInboundPollingService


class InboundPollingTest(TestCase):
    @patch('apps.qbo.services.QBOService.get_client', return_value=None)
    def test_orchestrator_reports_both_branches_without_connection(self, _m):
        stats = QBOInboundPollingService.poll_all()
        self.assertIn('invoices', stats)
        self.assertIn('bills', stats)
        self.assertEqual(stats['bills'].get('error'), 'No active QBO connection')
