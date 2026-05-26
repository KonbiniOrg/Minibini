from apps.core.management.base import ScheduledProcessCommand, SkipRun
from apps.qbo.services import QBOPaymentPollingService


class Command(ScheduledProcessCommand):
    help = 'Poll QuickBooks Online for invoice payment status and update Minibini status.'
    process_name = 'poll_qbo_payments'

    def run(self):
        stats = QBOPaymentPollingService.poll_all()
        if 'error' in stats:
            raise SkipRun(stats['error'])
        return {
            'checked': stats['checked'],
            'transitioned': stats['transitioned'],
            'cache_updated': stats['cache_updated'],
            'errors': stats['errors'],
        }
