"""
Tests for earmark release when a Job transitions into work_complete.
"""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.inventory.models import InventoryItem, Earmark


class EarmarkReleaseOnWorkCompleteTest(TestCase):

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-REL-001', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )
        # Walk to in_progress so tests can transition directly to work_complete.
        self.job.status = Job.STATUS_IN_PROGRESS
        self.job.save()
        self.category = AccountingCategory.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False},
        )[0]
        self.plywood = InventoryItem.objects.create(
            code='PLY.REL', description='Plywood',
            units='sheet', qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            accounting_category=self.category,
        )

    def test_earmarks_released_on_job_work_complete(self):
        """Remaining earmarks for the job are deleted when job enters work_complete."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job,
            quantity=Decimal('3.00'),
        )
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 1)

        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_partial_earmark_released_on_complete(self):
        """Even partially consumed earmarks are cleaned up."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job,
            quantity=Decimal('1.50'),
        )

        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_no_error_when_no_earmarks_on_complete(self):
        """Transitioning with no earmarks doesn't error."""
        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_other_job_earmarks_untouched(self):
        """Completing one job doesn't affect another job's earmarks."""
        other_job = Job.objects.create(
            job_number='J-REL-002', contact=self.contact,
        )
        Earmark.objects.create(
            inventory_item=self.plywood, job=other_job,
            quantity=Decimal('5.00'),
        )
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job,
            quantity=Decimal('3.00'),
        )

        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)
        self.assertEqual(Earmark.objects.filter(job=other_job).count(), 1)


class EarmarkReleaseTransitionTest(TestCase):
    """Regression tests for the release_earmarks_for_job hook firing."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test2@example.com', work_number='555-0200',
        )
        self.job = Job.objects.create(
            job_number='J-REL-T-001', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )
        # Walk to in_progress (valid step before work_complete).
        self.job.status = Job.STATUS_IN_PROGRESS
        self.job.save()

    def test_release_called_on_approved_to_work_complete(self):
        """Transitioning IN_PROGRESS -> WORK_COMPLETE releases earmarks exactly once."""
        with patch(
            'apps.inventory.services.InventoryService.release_earmarks_for_job'
        ) as mock_release:
            JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)
        self.assertEqual(mock_release.call_count, 1)

    def test_noop_transition_does_not_release(self):
        """Transitioning WORK_COMPLETE -> WORK_COMPLETE is a no-op and doesn't release."""
        self.job.status = Job.STATUS_WORK_COMPLETE
        self.job.save(update_fields=['status'])

        with patch(
            'apps.inventory.services.InventoryService.release_earmarks_for_job'
        ) as mock_release:
            JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)
        mock_release.assert_not_called()

    def test_work_complete_to_completed_does_not_release_again(self):
        """Transitioning WORK_COMPLETE -> COMPLETED does not re-release earmarks."""
        self.job.status = Job.STATUS_WORK_COMPLETE
        self.job.save(update_fields=['status'])

        with patch(
            'apps.inventory.services.InventoryService.release_earmarks_for_job'
        ) as mock_release:
            JobService.update_status(self.job.pk, Job.STATUS_COMPLETED)
        mock_release.assert_not_called()


class EarmarkReleaseOnTerminalStatusesTest(TestCase):
    """Bug 5: earmarks release on entry to CANCELLED and REJECTED too, and the
    release fires through the consolidated update_job regardless of path."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='T', last_name='C', email='t5@c.com',
        )
        self.category = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False},
        )[0]
        self.pli = InventoryItem.objects.create(
            code='PLY.T5', description='Plywood', units='sheet',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            accounting_category=self.category,
        )

    def _job(self, *statuses):
        job = Job.objects.create(
            job_number=f'J-T5-{Job.objects.count()}', contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        for s in statuses:
            job.status = s
            job.save()
        return job

    def _earmark(self, job, qty='3.00'):
        return Earmark.objects.create(
            inventory_item=self.pli, job=job, quantity=Decimal(qty),
        )

    def test_cancel_releases_earmarks(self):
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        self._earmark(job)
        JobService.update_job(job.pk, status=Job.STATUS_CANCELLED)
        self.assertEqual(Earmark.objects.filter(job=job).count(), 0)

    def test_reject_releases_earmarks(self):
        job = self._job()  # draft
        self._earmark(job)
        JobService.update_job(job.pk, status=Job.STATUS_REJECTED)
        self.assertEqual(Earmark.objects.filter(job=job).count(), 0)

    def test_work_complete_via_update_job_releases_earmarks(self):
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                        Job.STATUS_IN_PROGRESS)
        self._earmark(job)
        JobService.update_job(job.pk, status=Job.STATUS_WORK_COMPLETE)
        self.assertEqual(Earmark.objects.filter(job=job).count(), 0)

    def test_non_status_update_does_not_release(self):
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        self._earmark(job)
        JobService.update_job(job.pk, name='Renamed')
        self.assertEqual(Earmark.objects.filter(job=job).count(), 1)

    def test_reactivation_does_not_recreate_earmarks(self):
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        self._earmark(job)
        JobService.update_job(job.pk, status=Job.STATUS_CANCELLED)
        self.assertEqual(Earmark.objects.filter(job=job).count(), 0)
        JobService.update_job(job.pk, status=Job.STATUS_IN_PROGRESS)
        self.assertEqual(Earmark.objects.filter(job=job).count(), 0)
