from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstWorksheet
from apps.estimates.services import EstimateWizardService, EstimateClaimConflict
from apps.jobs.models import Job


class OpenForWorksheetTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_creates_draft_estimate_when_none_exists(self):
        est = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(est.job, self.job)
        self.ws.refresh_from_db()
        self.assertEqual(self.ws.estimate, est)

    def test_returns_existing_draft(self):
        first = EstimateWizardService.open_for_worksheet(self.ws)
        second = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(first.pk, second.pk)

    def test_refuses_finalized_worksheet(self):
        self.ws.status = EstWorksheet.STATUS_FINAL
        self.ws.save()
        with self.assertRaises(ValidationError):
            EstimateWizardService.open_for_worksheet(self.ws)


class ClaimConflictExceptionTest(TestCase):
    def test_exception_carries_atom_ids(self):
        exc = EstimateClaimConflict(atom_ids=[{'type': 'plan_charge', 'id': 1}])
        self.assertEqual(exc.atom_ids, [{'type': 'plan_charge', 'id': 1}])
