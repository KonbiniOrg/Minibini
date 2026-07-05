"""Pinning tests for two LATER verifications (2026-07-04).

1. RateScheme.supersede() does NOT repoint catalog users — a ServiceItem (or
   Task) keeps pointing at the old, renamed scheme. Confirmed behavior, now
   pinned: the deferred-service crystallization tolerates this via
   generate_task(allow_superseded_scheme=True), and template-based creation
   rejects superseded-scheme templates loudly.

2. One-live-estimate-tree-per-job is a service-level invariant, not just an
   API-layer check: EstimateService.create_for_job refuses a second
   non-superseded estimate. revise_estimate remains the versioning path.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import Estimate, ServiceItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job, RateScheme, Task


class SupersedeDoesNotRepointTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='sup', code='SUP')
        self.scheme = RateScheme.objects.create(
            name='Bench rate', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50'), unit_label='hr', accounting_category=self.cat,
        )

    def test_service_item_keeps_old_scheme(self):
        si = ServiceItem.objects.create(
            template_name='Bench work', rate_scheme=self.scheme,
        )
        new = self.scheme.supersede(rate=Decimal('60'))
        si.refresh_from_db()
        self.assertEqual(si.rate_scheme_id, self.scheme.pk)
        self.assertNotEqual(si.rate_scheme_id, new.pk)
        self.scheme.refresh_from_db()
        self.assertEqual(self.scheme.replaced_by_id, new.pk)
        self.assertIn('(v1)', self.scheme.name)

    def test_task_keeps_old_scheme(self):
        contact = Contact.objects.create(first_name='S', last_name='D')
        job = Job.objects.create(job_number='JOB-SUP-1', contact=contact)
        task = Task.objects.create(job=job, name='T', rate_scheme=self.scheme)
        new = self.scheme.supersede(rate=Decimal('60'))
        task.refresh_from_db()
        self.assertEqual(task.rate_scheme_id, self.scheme.pk)
        self.assertNotEqual(task.rate_scheme_id, new.pk)


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
