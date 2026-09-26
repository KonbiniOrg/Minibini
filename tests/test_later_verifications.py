"""Pinning test for a LATER verification (2026-07-04).

One-live-estimate-tree-per-job is a service-level invariant, not just an
API-layer check: EstimateService.create_for_job refuses a second
non-superseded estimate. revise_estimate remains the versioning path.

(A second pinning class used to live here — RateScheme.supersede() not
repointing catalog users. Task 4 deletes supersede() entirely: presets are
freely editable in place now, so there's no "old scheme" to keep pointing
at and nothing left to pin. See tests/test_rate_scheme_retire.py for the
Task 4 replacement coverage.)
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.jobs.models import Job


class OneLiveEstimateTreeServiceGuardTest(TestCase):
    def setUp(self):
        contact = Contact.objects.create(first_name='O', last_name='C')
        self.job = Job.objects.create(job_number='JOB-OLE-1', contact=contact)

    def test_second_estimate_refused_at_service_layer(self):
        EstimateService.create_for_job(self.job.pk)
        with self.assertRaises(ValidationError):
            EstimateService.create_for_job(self.job.pk)

    def test_superseded_estimates_continue_via_revision_not_a_new_tree(self):
        # The guard excludes superseded rows, but a brand-new tree still can't
        # coexist with them: the (estimate_number, version) uniqueness means a
        # second v1 collides. Revision (revise_estimate) is the only
        # continuation — which is exactly the invariant's intent.
        est = EstimateService.create_for_job(self.job.pk)
        Estimate.objects.filter(pk=est.pk).update(
            status=Estimate.STATUS_SUPERSEDED)
        with self.assertRaises(ValidationError):
            EstimateService.create_for_job(self.job.pk)
