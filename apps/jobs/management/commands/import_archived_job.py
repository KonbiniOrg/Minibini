import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import User
from apps.jobs.archive import ArchiveImportService


class Command(BaseCommand):
    help = (
        'Import archived job(s) from a JSON file (one payload object or a list of '
        'payloads). Stops at the first invalid payload; earlier ones stay imported.'
    )

    def add_arguments(self, parser):
        parser.add_argument('path', help='JSON file with one payload or a list of payloads')
        parser.add_argument('--user', help='Username to attribute history to (default: first superuser)')

    def handle(self, *args, **options):
        if options['user']:
            try:
                user = User.objects.get(username=options['user'])
            except User.DoesNotExist:
                raise CommandError(f"User '{options['user']}' does not exist.")
        else:
            user = User.objects.filter(is_superuser=True).order_by('pk').first()

        try:
            with open(options['path']) as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise CommandError(f'Cannot read {options["path"]}: {e}')
        payloads = data if isinstance(data, list) else [data]

        for index, payload in enumerate(payloads):
            try:
                job = ArchiveImportService.create_archived_job(payload, user=user)
            except ValidationError as e:
                if hasattr(e, 'error_dict'):
                    for field, msgs in e.message_dict.items():
                        for msg in msgs:
                            self.stderr.write(f'payload[{index}]: {field}: {msg}')
                else:
                    for msg in e.messages:
                        self.stderr.write(f'payload[{index}]: {msg}')
                raise CommandError(f'Payload {index} failed validation; nothing further imported.')
            self.stdout.write(f'Imported {job.job_number} (pk {job.pk})')
