from django.core.management.base import BaseCommand
from apps.qbo.services import QBOPaymentPollingService


class Command(BaseCommand):
    help = 'Poll QuickBooks Online for payment status updates on synced invoices'

    def handle(self, *args, **options):
        self.stdout.write('Polling QBO for payment status updates...')

        stats = QBOPaymentPollingService.poll_all()

        if 'error' in stats:
            self.stderr.write(self.style.ERROR(f"Error: {stats['error']}"))
            return

        self.stdout.write(
            f"Checked: {stats['checked']}, "
            f"Updated: {stats['updated']}, "
            f"Errors: {len(stats['errors'])}"
        )

        for error in stats['errors']:
            self.stderr.write(self.style.WARNING(f"  {error}"))

        if stats['updated'] > 0:
            self.stdout.write(self.style.SUCCESS(
                f"Updated {stats['updated']} invoice(s)"
            ))
