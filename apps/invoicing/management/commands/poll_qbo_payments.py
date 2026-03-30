from django.core.management.base import BaseCommand
from apps.qbo.services import QBOPaymentPollingService, QBOBillPaymentPollingService


class Command(BaseCommand):
    help = 'Poll QuickBooks Online for payment status updates on synced invoices and bills'

    def handle(self, *args, **options):
        self.stdout.write('Polling QBO for payment status updates...')

        # Poll invoices
        inv_stats = QBOPaymentPollingService.poll_all()
        if 'error' in inv_stats:
            self.stderr.write(self.style.ERROR(f"Invoice polling error: {inv_stats['error']}"))
        else:
            self.stdout.write(
                f"Invoices — Checked: {inv_stats['checked']}, "
                f"Updated: {inv_stats['updated']}, "
                f"Errors: {len(inv_stats['errors'])}"
            )
            for error in inv_stats['errors']:
                self.stderr.write(self.style.WARNING(f"  {error}"))

        # Poll bills
        bill_stats = QBOBillPaymentPollingService.poll_all()
        if 'error' in bill_stats:
            self.stderr.write(self.style.ERROR(f"Bill polling error: {bill_stats['error']}"))
        else:
            self.stdout.write(
                f"Bills — Checked: {bill_stats['checked']}, "
                f"Updated: {bill_stats['updated']}, "
                f"Errors: {len(bill_stats['errors'])}"
            )
            for error in bill_stats['errors']:
                self.stderr.write(self.style.WARNING(f"  {error}"))

        total_updated = inv_stats.get('updated', 0) + bill_stats.get('updated', 0)
        if total_updated > 0:
            self.stdout.write(self.style.SUCCESS(f"Total updated: {total_updated}"))
