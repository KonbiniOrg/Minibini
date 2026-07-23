"""The seed-setup-defaults data migration: a migrate-only database (no
fixtures) must be able to create Jobs/POs and use units out of the box."""
import json

from django.test import TestCase

from apps.core.models import AppState, Configuration
from apps.core.units import DEFAULT_UNITS


class SeededDefaultsTest(TestCase):
    """The test DB is built from migrations alone — these rows must exist."""

    def test_appstate_counters_seeded(self):
        self.assertEqual(AppState.objects.get(key='job_counter').value, '0')
        self.assertEqual(AppState.objects.get(key='po_counter').value, '0')

    def test_number_patterns_seeded(self):
        self.assertEqual(
            Configuration.objects.get(key='job_number_sequence').value,
            'JOB-{year}-{counter:04d}')
        self.assertEqual(
            Configuration.objects.get(key='po_number_sequence').value,
            'PO-{year}-{counter:04d}')

    def test_units_list_seeded(self):
        self.assertEqual(
            json.loads(Configuration.objects.get(key='units_list').value),
            DEFAULT_UNITS)

    def test_seed_is_idempotent_and_preserves_existing(self):
        from apps.core.migrations import _seed_setup_defaults as seeder
        AppState.objects.filter(key='job_counter').delete()
        AppState.objects.create(key='job_counter', value='42')
        Configuration.objects.filter(key='units_list').update(value='["none","furlongs"]')
        from django.apps import apps as global_apps
        seeder.seed(global_apps, None)
        self.assertEqual(AppState.objects.get(key='job_counter').value, '42')
        self.assertEqual(
            Configuration.objects.get(key='units_list').value,
            '["none","furlongs"]')
        # po_counter was untouched and still present exactly once
        self.assertEqual(AppState.objects.filter(key='po_counter').count(), 1)

    def test_job_creation_works_on_migrate_only_db(self):
        """The whole point of the seed: JobService.create_job (the normal
        path, which auto-generates the number) works with zero fixtures."""
        from apps.contacts.models import Contact
        from apps.jobs.services import JobService
        contact = Contact.objects.create(
            first_name='Fresh', last_name='Tenant',
            email='fresh@example.com', mobile_number='555-0000')
        job = JobService.create_job(contact=contact)
        self.assertTrue(job.job_number.startswith('JOB-'))
