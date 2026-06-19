from apps.core.management.base import ScheduledProcessCommand, SkipRun
from apps.qbo.services import QBOInboundPollingService


class Command(ScheduledProcessCommand):
    help = 'Poll QuickBooks Online for inbound payment/clearance updates.'
    process_name = 'poll_qbo_payments'

    def run(self):
        stats = QBOInboundPollingService.poll_all()
        inv = stats['invoices']
        if 'error' in inv:
            raise SkipRun(inv['error'])
        return {
            'checked': inv['checked'],
            'transitioned': inv['transitioned'],
            'cache_updated': inv['cache_updated'],
            'errors': inv['errors'],
            'bills_checked': stats['bills'].get('checked', 0),
            'bills_cleared': stats['bills'].get('cleared', 0),
        }
