"""Task 1 (Tasks-page CO-lens plan): one-draft-change-order-per-job is
enforced in ChangeOrder.clean(), mirroring Estimate.clean()'s one-draft-
estimate invariant — every creation path (ChangeOrderService.create,
seed_new, the seed-new API action) is bound automatically via
ChangeOrder.save() -> full_clean(). Draft-vs-draft only:
request_changes's seed_new(move_claims=True) supersedes the source CO
BEFORE seeding the new draft, so that transient (superseded source +
new draft) must not trip it.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import Estimate, ChangeOrder, ChangeOrderLineItem
from apps.jobs.models import Job


def _advance_job_to_on_hold(job):
    """Draft -> submitted -> approved, then hold (on_hold flag)."""
    from apps.jobs.services import JobService
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        job.status = s
        job.save()
    JobService.hold_job(job.pk, 'CO editing')
    job.refresh_from_db()


def _make_accepted_estimate(job, number='EST-CDU-1'):
    return Estimate.objects.create(
        job=job, estimate_number=number, version=1,
        status=Estimate.STATUS_ACCEPTED,
    )


class DraftChangeOrderUniquenessTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'),
            units='ea', sort_order=10,
        )
        _advance_job_to_on_hold(self.job)

    def test_second_draft_via_create_is_refused(self):
        ChangeOrderService.create(job_id=self.job.pk)
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.create(job_id=self.job.pk)
        self.assertIn('already has a draft change order', str(ctx.exception))

    def test_second_draft_via_seed_new_from_a_draft_source_is_refused(self):
        # seed_new's docstring frames its standalone caller as expecting a
        # TERMINAL source CO; calling it on a still-draft source would (pre-
        # invariant) silently mint a second draft. Confirm the invariant now
        # refuses this rather than letting two drafts coexist.
        co = ChangeOrderService.create(job_id=self.job.pk)
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.seed_new(co.pk)
        self.assertIn('already has a draft change order', str(ctx.exception))

    def test_request_changes_reseed_still_works(self):
        # request_changes supersedes the open CO (status -> SUPERSEDED,
        # saved) BEFORE seed_new creates the new draft — so the new draft
        # never coexists with a draft sibling. Must not trip the invariant.
        co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), price=Decimal('200'),
            line_number=1, accounting_category_id=901,
        )
        ChangeOrderService.mark_open(co.pk)
        co.refresh_from_db()

        new_co = ChangeOrderService.request_changes(
            co.pk, {'contact_id': None, 'email': 'pat@acme.com', 'reason': 'cheaper'})
        self.assertEqual(new_co.status, ChangeOrder.STATUS_DRAFT)
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_SUPERSEDED)

    def test_seed_new_from_terminal_co_still_works(self):
        # The ordinary "seed a new draft from this one" action on a terminal
        # (rejected) source CO — no coexisting draft, must not trip.
        co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), price=Decimal('200'),
            line_number=1, accounting_category_id=901,
        )
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_REJECTED)
        co.refresh_from_db()

        new_co = ChangeOrderService.seed_new(co.pk)
        self.assertEqual(new_co.status, ChangeOrder.STATUS_DRAFT)

    def test_draft_can_still_be_edited_and_saved(self):
        # The check must exclude self — resaving the only draft is fine.
        co = ChangeOrderService.create(job_id=self.job.pk)
        co.save()
