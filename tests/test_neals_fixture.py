import os
import unittest
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
        # every Task has a rate_scheme (it is a NOT NULL FK)
        self.assertEqual(Task.objects.filter(rate_scheme__isnull=True).count(), 0)
        # every Job with a non-draft estimate has at least one Deliverable
        for est in Estimate.objects.exclude(status='draft'):
            self.assertTrue(
                Deliverable.objects.filter(job=est.job).exists(),
                f'Job {est.job_id} has a non-draft estimate but no Deliverable',
            )
