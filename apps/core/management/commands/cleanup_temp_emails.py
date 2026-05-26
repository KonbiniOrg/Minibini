from apps.core.management.base import ScheduledProcessCommand
from apps.core.services import EmailService


class Command(ScheduledProcessCommand):
    help = 'Delete cached TempEmail rows older than the configured retention period.'
    process_name = 'cleanup_temp_emails'

    def run(self):
        deleted = EmailService().cleanup_old_temp_emails()
        return {'deleted': deleted}
