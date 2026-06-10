from datetime import timedelta
from apps.core.history import record_history
from apps.core.models import JobHistory
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from apps.core.models import (
    Configuration, EmailRecord, TempEmail, ScheduledProcessRun
)
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder, Bill


class CleanupTempEmailsCommandTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='email_retention_days', value='90')

    def _make_temp(self, message_id, age_days, **rec_kwargs):
        rec = EmailRecord.objects.create(message_id=message_id, **rec_kwargs)
        temp = TempEmail.objects.create(
            email_record=rec, uid='u-' + message_id, subject='s',
            from_email='a@b.com', to_email='c@d.com',
            date_sent=timezone.now(),
        )
        # created_at is auto_now_add; backdate via update() to bypass it.
        TempEmail.objects.filter(pk=temp.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        return rec, temp

    def _record_status_change(self, object_type, object_id, new_status, days_ago):
        """Create a  recording a transition into new_status at
        a backdated timestamp. timestamp is auto_now_add so we rewrite it."""
        h = record_history(
            entry_type='audit',
            object_type=object_type,
            object_id=object_id,
            changes={'status': {'old': 'in_progress', 'new': new_status}},
        )
        type(h).objects.filter(pk=h.pk).update(
            timestamp=timezone.now() - timedelta(days=days_ago)
        )
        return h

    # --- existing behavior: unlinked emails ----------------------------------

    def test_deletes_old_keeps_recent_preserves_record(self):
        old_rec, _ = self._make_temp('old', 120)
        new_rec, _ = self._make_temp('new', 10)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=old_rec).exists())
        self.assertTrue(TempEmail.objects.filter(email_record=new_rec).exists())
        # Permanent records survive regardless.
        self.assertTrue(EmailRecord.objects.filter(pk=old_rec.pk).exists())

    def test_writes_run_record(self):
        self._make_temp('old', 120)
        call_command('cleanup_temp_emails')
        run = ScheduledProcessRun.objects.get(process_name='cleanup_temp_emails')
        self.assertEqual(run.outcome, 'ok')
        self.assertEqual(run.summary, {'deleted': 1})

    # --- linked to a Job -----------------------------------------------------

    _contact_counter = 0

    def _make_contact(self):
        CleanupTempEmailsCommandTest._contact_counter += 1
        n = CleanupTempEmailsCommandTest._contact_counter
        return Contact.objects.create(
            first_name=f'C{n}', last_name='X',
            email=f'c{n}@x.com', mobile_number=f'555-{n}',
        )

    def _make_business(self, name):
        c = self._make_contact()
        return Business.objects.create(business_name=name, default_contact=c)

    def test_linked_active_job_kept_even_if_email_old(self):
        contact = self._make_contact()
        job = Job.objects.create(
            job_number='JOB-A', name='active', status=Job.STATUS_IN_PROGRESS,
            contact=contact,
        )
        rec, _ = self._make_temp('linked-active', 999, job=job)

        call_command('cleanup_temp_emails')

        self.assertTrue(TempEmail.objects.filter(email_record=rec).exists())

    def test_linked_completed_job_old_transition_purged(self):
        contact = self._make_contact()
        job = Job.objects.create(
            job_number='JOB-B', name='done long ago', status=Job.STATUS_COMPLETED,
            contact=contact,
        )
        self._record_status_change('job', job.pk, Job.STATUS_COMPLETED, days_ago=120)
        rec, _ = self._make_temp('linked-old-done', 10, job=job)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=rec).exists())

    def test_linked_completed_job_recent_transition_kept(self):
        contact = self._make_contact()
        job = Job.objects.create(
            job_number='JOB-C', name='just finished', status=Job.STATUS_COMPLETED,
            contact=contact,
        )
        self._record_status_change('job', job.pk, Job.STATUS_COMPLETED, days_ago=30)
        rec, _ = self._make_temp('linked-recent-done', 999, job=job)

        call_command('cleanup_temp_emails')

        self.assertTrue(TempEmail.objects.filter(email_record=rec).exists())

    def test_linked_rejected_job_old_transition_purged(self):
        contact = self._make_contact()
        job = Job.objects.create(
            job_number='JOB-D', name='rejected', status=Job.STATUS_REJECTED,
            contact=contact,
        )
        self._record_status_change('job', job.pk, Job.STATUS_REJECTED, days_ago=200)
        rec, _ = self._make_temp('linked-rejected', 10, job=job)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=rec).exists())

    def test_linked_cancelled_job_treated_as_final(self):
        # User chose "Practically done" — CANCELLED counts as final.
        contact = self._make_contact()
        job = Job.objects.create(
            job_number='JOB-E', name='cancelled', status=Job.STATUS_CANCELLED,
            contact=contact,
        )
        self._record_status_change('job', job.pk, Job.STATUS_CANCELLED, days_ago=120)
        rec, _ = self._make_temp('linked-cancelled', 10, job=job)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=rec).exists())

    # --- linked to a PurchaseOrder ------------------------------------------

    def test_linked_active_po_kept(self):
        biz = self._make_business('V')
        po = PurchaseOrder.objects.create(
            po_number='PO-A', business=biz, status=PurchaseOrder.STATUS_ISSUED,
        )
        rec, _ = self._make_temp('po-active', 999, purchase_order=po)

        call_command('cleanup_temp_emails')

        self.assertTrue(TempEmail.objects.filter(email_record=rec).exists())

    def test_linked_received_po_old_transition_purged(self):
        biz = self._make_business('V2')
        po = PurchaseOrder.objects.create(
            po_number='PO-B', business=biz, status=PurchaseOrder.STATUS_RECEIVED_IN_FULL,
        )
        self._record_status_change(
            'purchaseorder', po.pk, PurchaseOrder.STATUS_RECEIVED_IN_FULL, days_ago=120,
        )
        rec, _ = self._make_temp('po-old-done', 10, purchase_order=po)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=rec).exists())

    def test_linked_cancelled_po_old_transition_purged(self):
        biz = self._make_business('V3')
        po = PurchaseOrder.objects.create(
            po_number='PO-C', business=biz, status=PurchaseOrder.STATUS_CANCELLED,
        )
        self._record_status_change(
            'purchaseorder', po.pk, PurchaseOrder.STATUS_CANCELLED, days_ago=200,
        )
        rec, _ = self._make_temp('po-cancelled', 10, purchase_order=po)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=rec).exists())

    # --- linked to a Bill ---------------------------------------------------

    def test_linked_paid_bill_old_transition_purged(self):
        biz = self._make_business('V4')
        bill = Bill.objects.create(
            vendor_invoice_number='BIL-A', business=biz,
            status=Bill.STATUS_PAID_IN_FULL,
        )
        self._record_status_change(
            'bill', bill.pk, Bill.STATUS_PAID_IN_FULL, days_ago=120,
        )
        rec, _ = self._make_temp('bill-paid', 10, bill=bill)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=rec).exists())

    def test_linked_refunded_bill_treated_as_final(self):
        biz = self._make_business('V5')
        bill = Bill.objects.create(
            vendor_invoice_number='BIL-B', business=biz,
            status=Bill.STATUS_REFUNDED,
        )
        self._record_status_change(
            'bill', bill.pk, Bill.STATUS_REFUNDED, days_ago=200,
        )
        rec, _ = self._make_temp('bill-refunded', 10, bill=bill)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=rec).exists())

    def test_linked_active_bill_kept(self):
        biz = self._make_business('V6')
        bill = Bill.objects.create(
            vendor_invoice_number='BIL-C', business=biz,
            status=Bill.STATUS_RECEIVED,
        )
        rec, _ = self._make_temp('bill-active', 999, bill=bill)

        call_command('cleanup_temp_emails')

        self.assertTrue(TempEmail.objects.filter(email_record=rec).exists())

    # --- multi-link (strictest: all must be purgeable) ----------------------

    def test_multi_link_one_active_keeps_email(self):
        contact = self._make_contact()
        active_job = Job.objects.create(
            job_number='JOB-MX1', name='active', status=Job.STATUS_IN_PROGRESS,
            contact=contact,
        )
        biz = self._make_business('Vmx')
        old_po = PurchaseOrder.objects.create(
            po_number='PO-MX1', business=biz,
            status=PurchaseOrder.STATUS_RECEIVED_IN_FULL,
        )
        self._record_status_change(
            'purchaseorder', old_po.pk, PurchaseOrder.STATUS_RECEIVED_IN_FULL,
            days_ago=120,
        )
        rec, _ = self._make_temp(
            'multi-mixed', 10, job=active_job, purchase_order=old_po,
        )

        call_command('cleanup_temp_emails')

        self.assertTrue(TempEmail.objects.filter(email_record=rec).exists())

    def test_multi_link_one_recent_finality_keeps_email(self):
        contact = self._make_contact()
        old_job = Job.objects.create(
            job_number='JOB-MX2', name='done long ago', status=Job.STATUS_COMPLETED,
            contact=contact,
        )
        self._record_status_change(
            'job', old_job.pk, Job.STATUS_COMPLETED, days_ago=200,
        )
        biz = self._make_business('Vmx2')
        recent_po = PurchaseOrder.objects.create(
            po_number='PO-MX2', business=biz,
            status=PurchaseOrder.STATUS_RECEIVED_IN_FULL,
        )
        self._record_status_change(
            'purchaseorder', recent_po.pk, PurchaseOrder.STATUS_RECEIVED_IN_FULL,
            days_ago=10,
        )
        rec, _ = self._make_temp(
            'multi-mixed-ages', 10, job=old_job, purchase_order=recent_po,
        )

        call_command('cleanup_temp_emails')

        self.assertTrue(TempEmail.objects.filter(email_record=rec).exists())

    def test_multi_link_all_final_and_old_purges_email(self):
        contact = self._make_contact()
        old_job = Job.objects.create(
            job_number='JOB-MX3', name='done', status=Job.STATUS_COMPLETED,
            contact=contact,
        )
        self._record_status_change(
            'job', old_job.pk, Job.STATUS_COMPLETED, days_ago=200,
        )
        biz = self._make_business('Vmx3')
        old_po = PurchaseOrder.objects.create(
            po_number='PO-MX3', business=biz,
            status=PurchaseOrder.STATUS_RECEIVED_IN_FULL,
        )
        self._record_status_change(
            'purchaseorder', old_po.pk, PurchaseOrder.STATUS_RECEIVED_IN_FULL,
            days_ago=150,
        )
        rec, _ = self._make_temp(
            'multi-all-done', 10, job=old_job, purchase_order=old_po,
        )

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=rec).exists())

    # --- finality fallback when no  ------------------------------

    def test_final_object_with_no_history_falls_back_to_email_date(self):
        # Pre-history-tracking object or one created in a final state directly.
        # Without a status-change , fall back to TempEmail.created_at.
        contact = self._make_contact()
        job = Job.objects.create(
            job_number='JOB-NH', name='no history', status=Job.STATUS_COMPLETED,
            contact=contact,
        )
        # Wipe any auto-history that the @history decorator may have recorded
        # so the test truly has none for this object.
        JobHistory.objects.filter(object_type='job', object_id=job.pk).delete()

        old_rec, _ = self._make_temp('nohist-old', 200, job=job)
        new_rec, _ = self._make_temp('nohist-new', 10, job=job)

        call_command('cleanup_temp_emails')

        self.assertFalse(TempEmail.objects.filter(email_record=old_rec).exists())
        self.assertTrue(TempEmail.objects.filter(email_record=new_rec).exists())

    # --- earlier finality entries don't override more-recent ones -----------

    def test_uses_most_recent_finality_transition(self):
        # Job that briefly entered a final status long ago, then was
        # reactivated, then re-finalized recently. Only the recent timestamp
        # matters.
        contact = self._make_contact()
        job = Job.objects.create(
            job_number='JOB-MR', name='roundtrip', status=Job.STATUS_COMPLETED,
            contact=contact,
        )
        self._record_status_change('job', job.pk, Job.STATUS_COMPLETED, days_ago=300)
        self._record_status_change('job', job.pk, Job.STATUS_COMPLETED, days_ago=10)
        rec, _ = self._make_temp('roundtrip', 10, job=job)

        call_command('cleanup_temp_emails')

        self.assertTrue(TempEmail.objects.filter(email_record=rec).exists())
