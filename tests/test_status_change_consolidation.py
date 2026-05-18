"""Bug 6: estimate- and invoice-driven Job status changes route through
JobService.update_job. The invoice-paid completion path releases any loose
pending materials (restocked) before completing, and records a HistoryEntry."""

from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, HistoryEntry
from apps.inventory.models import Earmark, PriceListItem
from apps.inventory.services import MaterialService
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.jobs.services import JobService


class ReleaseLooseMaterialsHelperTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='T', last_name='C', email='t6@c.com',
        )
        self.cat = AccountingCategory.objects.create(name='B6 Cat', code='B6')
        self.pli = PriceListItem.objects.create(
            code='I-B6', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('20'),
        )
        self.job = Job.objects.create(
            job_number='J-B6-H', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )
        self.job.status = Job.STATUS_IN_PROGRESS
        self.job.save()

    def test_release_loose_materials_restocks_and_reports(self):
        MaterialService.create_on_job(
            job=self.job, task=None, description='loose mat',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        released = JobService.release_loose_materials(self.job)
        self.assertEqual(len(released), 1)
        self.assertEqual(released[0]['description'], 'loose mat')
        self.assertEqual(
            JobService._loose_pending_materials(self.job).count(), 0,
        )

    def test_release_loose_materials_noop_when_none(self):
        self.assertEqual(JobService.release_loose_materials(self.job), [])


class InvoiceCompletionConsolidationTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Inv', last_name='C', email='inv6@c.com',
        )
        self.cat = AccountingCategory.objects.create(name='B6 Inv Cat', code='B6I')
        self.pli = PriceListItem.objects.create(
            code='I-B6I', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('20'),
        )

    def _job(self, status):
        job = Job.objects.create(
            job_number=f'J-B6I-{Job.objects.count()}', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )
        if status != Job.STATUS_APPROVED:
            for s in (Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE):
                job.status = s
                job.save()
                if s == status:
                    break
        return job

    def _pay_invoice(self, job):
        inv = Invoice.objects.create(
            job=job, invoice_number=f'INV-B6-{Invoice.objects.count()}',
            status=Invoice.STATUS_OPEN,
        )
        inv.status = Invoice.STATUS_PAID
        inv.save()

    def test_invoice_completion_releases_earmarks(self):
        job = self._job(Job.STATUS_APPROVED)
        Earmark.objects.create(
            price_list_item=self.pli, job=job, quantity=Decimal('3'),
        )
        self._pay_invoice(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_COMPLETED)
        self.assertEqual(Earmark.objects.filter(job=job).count(), 0)

    def test_invoice_completion_releases_loose_materials_and_logs(self):
        job = self._job(Job.STATUS_APPROVED)
        MaterialService.create_on_job(
            job=job, task=None, description='loose-on-invoice',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        self._pay_invoice(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_COMPLETED)
        self.assertEqual(JobService._loose_pending_materials(job).count(), 0)
        entries = HistoryEntry.objects.filter(
            object_type='job', object_id=job.pk,
        )
        self.assertTrue(
            any('Loose materials released' in str(e.changes) for e in entries)
        )
