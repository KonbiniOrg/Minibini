"""The committed developer seed must load into a database built from the
current migrations alone, and the data validator must run over it.

`fixtures/large_datasets/nealseed.json` is the fixture a new developer (and
the deploy step) loads right after `migrate`; nothing else exercises it. The
fixture is RM-managed — if this fails after a schema change, report it, do
not regenerate the file.
"""
import os
import unittest
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.jobs.models import Job, Task

FIXTURE = 'fixtures/large_datasets/nealseed.json'


@unittest.skipUnless(os.path.exists(FIXTURE), 'nealseed.json not present')
class NealseedFixtureLoadTest(TestCase):
    def test_loads_on_a_migrate_only_database_and_validates(self):
        # Raises on any FK / field / schema mismatch.
        call_command('loaddata', FIXTURE, verbosity=0)
        self.assertGreater(Job.objects.count(), 0)
        self.assertGreater(Task.objects.count(), 0)
        # validate_data reports rather than raises; it must at least run to
        # completion over every check against the real seed.
        out = StringIO()
        call_command('validate_data', stdout=out)
        self.assertIn('error', out.getvalue().lower())
