import json
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.core.models import User
from apps.jobs.models import Job
from tests.test_contacts_status import make_business


class ImportArchivedJobCommandTests(TestCase):
    def setUp(self):
        _, self.contact, _ = make_business()
        User.objects.create_superuser(username='root', password='x', email='r@x.test')
        self.dir = tempfile.mkdtemp()

    def _write(self, data):
        path = os.path.join(self.dir, 'payload.json')
        with open(path, 'w') as f:
            json.dump(data, f)
        return path

    def _run(self, path, **kw):
        out, err = StringIO(), StringIO()
        try:
            call_command('import_archived_job', path, stdout=out, stderr=err, **kw)
        finally:
            self.out, self.err = out.getvalue(), err.getvalue()

    def test_imports_list_of_payloads(self):
        path = self._write([
            {'job_number': 'CMD-1', 'contact': self.contact.pk},
            {'job_number': 'CMD-2', 'contact': self.contact.pk},
        ])
        self._run(path)
        self.assertEqual(Job.objects.filter(status=Job.STATUS_ARCHIVED).count(), 2)
        self.assertIn('Imported CMD-1 (pk ', self.out)
        self.assertIn('Imported CMD-2 (pk ', self.out)

    def test_single_object_payload(self):
        self._run(self._write({'job_number': 'CMD-1', 'contact': self.contact.pk}))
        self.assertTrue(Job.objects.filter(job_number='CMD-1').exists())

    def test_invalid_second_payload_stops_and_reports(self):
        path = self._write([
            {'job_number': 'CMD-1', 'contact': self.contact.pk},
            {'job_number': 'CMD-2', 'contact': 999999},
            {'job_number': 'CMD-3', 'contact': self.contact.pk},
        ])
        with self.assertRaises(CommandError):
            self._run(path)
        self.assertTrue(Job.objects.filter(job_number='CMD-1').exists())
        self.assertFalse(Job.objects.filter(job_number='CMD-2').exists())
        self.assertFalse(Job.objects.filter(job_number='CMD-3').exists())
        self.assertIn('contact', self.err)

    def test_unknown_user_is_command_error(self):
        path = self._write({'job_number': 'CMD-1', 'contact': self.contact.pk})
        with self.assertRaises(CommandError):
            self._run(path, user='nobody')
        self.assertFalse(Job.objects.filter(job_number='CMD-1').exists())

    def test_named_user_accepted(self):
        User.objects.create_user(username='bob', password='x', email='b@x.test')
        self._run(self._write({'job_number': 'CMD-1', 'contact': self.contact.pk}), user='bob')
        self.assertIn('Imported CMD-1', self.out)
