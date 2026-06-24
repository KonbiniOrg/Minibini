import os
import unittest
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from apps.jobs.models import Job, Task
from apps.estimates.models import Estimate
from apps.deliverables.models import Deliverable

FIXTURE = 'nealsdata/datasets/converted.json'


@unittest.skipUnless(os.path.exists(FIXTURE), 'converted.json not generated')
class NealsFixtureLoadTest(TestCase):
    def test_fixture_loads_into_test_db(self):
        # Loads into the auto-created TEST database; raises on any
        # FK / field / schema mismatch.
        call_command('loaddata', FIXTURE, verbosity=0)
        self.assertGreater(Job.objects.count(), 0)
        # every Task has a service_price (it is a NOT NULL FK)
        self.assertEqual(Task.objects.filter(service_price__isnull=True).count(), 0)
        # every Job with a non-draft estimate has at least one Deliverable
        for est in Estimate.objects.exclude(status='draft'):
            self.assertTrue(
                Deliverable.objects.filter(job=est.job).exists(),
                f'Job {est.job_id} has a non-draft estimate but no Deliverable',
            )

    def test_validate_data_runs_on_fixture(self):
        # The validate_data command must run to completion against the
        # generated fixture (it reports issues, it does not raise on them) —
        # this exercises every check_* method against real converter output.
        call_command('loaddata', FIXTURE, verbosity=0)
        out = StringIO()
        call_command('validate_data', stdout=out)
        # It always prints an error summary line ('N error(s)' or 'No errors').
        self.assertIn('error', out.getvalue().lower())

    def test_bleps_and_shifts_loaded_and_invariants_hold(self):
        # Bleps + Shifts are present, and the time-tracking invariants
        # (enclosure / no per-user overlap / task-not-pending) report no errors.
        from apps.jobs.models import Blep
        from apps.core.models import Shift
        call_command('loaddata', FIXTURE, verbosity=0)
        self.assertGreater(Blep.objects.count(), 0)
        self.assertGreater(Shift.objects.count(), 0)
        out = StringIO()
        call_command('validate_data', stdout=out)
        text = out.getvalue()
        for marker in ('not enclosed by any shift', 'overlaps blep',
                       'is pending but has a blep'):
            self.assertNotIn(marker, text, f'validate_data reported: {marker}')
