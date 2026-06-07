import os
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()


class Command(BaseCommand):
    """
    Generic base class for populating data from fixtures.
    Subclasses only need to specify the fixture_dir attribute.
    """
    help = 'Drop and recreate database with data for development'

    # Subclasses must override this to specify their fixture directory
    fixture_dir = None  # e.g., 'job_data', 'contact_data', etc.

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-drop',
            action='store_true',
            help='Skip dropping the database (useful if database is already empty)',
        )
        parser.add_argument(
            '--skip-user',
            action='store_true',
            help='Skip creating the default development user',
        )

    def get_fixture_dir(self):
        """Get the fixture directory path. Subclasses can override this for custom logic."""
        if self.fixture_dir is None:
            raise NotImplementedError(
                "Subclasses must define fixture_dir attribute or override get_fixture_dir()"
            )
        return os.path.join('fixtures', self.fixture_dir)

    def get_data_type_name(self):
        """Get a human-readable name for the data type being loaded."""
        if self.fixture_dir:
            return self.fixture_dir.replace('_', ' ').title()
        return "Data"

    # The four authorization atoms — granting all of them gives the dev user
    # full SPA access without relying on superuser (authorization is atoms-only).
    DEV_USER_ATOMS = [
        'can_manage_jobs',
        'can_manage_financials',
        'can_manage_time',
        'can_manage_config',
    ]

    def create_default_user(self):
        """Create the default development user. Can be overridden by subclasses.

        The user gets all four permission atoms (not superuser) — authorization
        is atoms-only. `is_staff` is kept for Django /admin/ login; create a
        superuser separately with `createsuperuser` if you need admin model
        access.
        """
        from django.contrib.auth.models import Permission
        user = User.objects.create_user(
            username='dev_user',
            email='dev@example.com',
            password='dev_password',
            first_name='Dev',
            last_name='User',
            is_staff=True,
        )
        user.user_permissions.add(*Permission.objects.filter(
            codename__in=self.DEV_USER_ATOMS,
            content_type__app_label='core',
        ))
        return user

    def handle(self, *args, **options):
        db_name = settings.DATABASES['default']['NAME']
        data_type = self.get_data_type_name()

        if not options['skip_drop']:
            self.stdout.write('Clearing all data from database...')

            try:
                # Use Django's flush command to clear all data
                # This preserves the database structure but removes all data
                call_command('flush', '--no-input', verbosity=0)
                self.stdout.write(self.style.SUCCESS('Database cleared.'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error clearing database: {e}'))
                return

        # Run migrations
        self.stdout.write('Running migrations...')
        try:
            call_command('migrate', '--no-input', verbosity=0)
            self.stdout.write(self.style.SUCCESS('Migrations completed.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error running migrations: {e}'))
            return

        # Create default development user
        if not options['skip_user']:
            self.stdout.write('Creating default development user...')
            try:
                default_user = self.create_default_user()
                self.stdout.write(self.style.SUCCESS('Default user created.'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error creating default user: {e}'))
                return

        # Load all fixtures from specified directory
        fixtures_dir = self.get_fixture_dir()
        if not os.path.exists(fixtures_dir):
            self.stdout.write(self.style.ERROR(f'Fixtures directory {fixtures_dir} does not exist.'))
            return

        # Get all JSON files in the directory, sorted alphabetically
        fixture_files = sorted([f for f in os.listdir(fixtures_dir) if f.endswith('.json')])

        if not fixture_files:
            self.stdout.write(self.style.WARNING(f'No fixture files found in {self.fixture_dir} directory.'))
            return

        self.stdout.write(f'Loading {len(fixture_files)} fixture files...')

        for fixture_file in fixture_files:
            fixture_path = os.path.join(fixtures_dir, fixture_file)
            self.stdout.write(f'  Loading {fixture_file}...')
            try:
                call_command('loaddata', fixture_path, verbosity=0)
                self.stdout.write(self.style.SUCCESS(f'    ✓ {fixture_file} loaded'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'    ✗ Error loading {fixture_file}: {e}'))
                return

        # Show summary of what was loaded
        self.stdout.write('\n' + self.style.SUCCESS(f'{data_type} populated successfully!'))