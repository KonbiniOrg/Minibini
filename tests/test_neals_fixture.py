import os
import unittest
from io import StringIO
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
        self.assertGreater(Task.objects.count(), 0)
        # every Job with a non-draft estimate has at least one Deliverable
        for est in Estimate.objects.exclude(status=Estimate.STATUS_DRAFT).exclude(
                job__status=Job.STATUS_ARCHIVED):
            self.assertTrue(
                Deliverable.objects.filter(job=est.job).exists(),
                f'Job {est.job_id} has a non-draft estimate but no Deliverable',
            )

    def test_deposits_load_as_the_app_models_them(self):
        """convert.md §4 "Deposits": every paired credit is a deduction of a
        real deposit line, and a standalone paid deposit is offered as a
        credit atom by the invoice wizard."""
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        from apps.invoicing.services import InvoiceWizardService
        call_command('loaddata', FIXTURE, verbosity=0)
        claims = list(InvoiceLineItemSource.objects.filter(
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT))
        self.assertTrue(claims, 'no deposit credits in the fixture')
        for cl in claims:
            credit = cl.invoice_line_item
            dep = InvoiceLineItem.objects.get(pk=cl.source_pk)
            self.assertTrue(credit.is_deposit_deduction)
            self.assertTrue(dep.is_deposit_line)
            self.assertEqual(dep.invoice.status, Invoice.STATUS_PAID)
            self.assertEqual(dep.invoice.job_id, credit.invoice.job_id)
        claimed = {cl.source_pk for cl in claims}
        standalone = [li for li in InvoiceLineItem.objects.filter(
            accounting_category__is_deposit=True, invoice__status=Invoice.STATUS_PAID)
            .exclude(invoice__job__status='archived')
            if li.pk not in claimed and li.is_deposit_line]
        self.assertTrue(standalone, 'no standalone paid deposit in the fixture')
        li = standalone[0]
        draft = Invoice.objects.create(job=li.invoice.job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(draft)
        offered = [a for grp in pool['tasks'] for a in grp.get('atoms', [])
                   if a.get('type') == 'deposit' and a.get('id') == li.pk]
        self.assertEqual(len(offered), 1, 'standalone deposit not offered as a credit atom')

    def test_archived_jobs_present_and_valid(self):
        # The converter archives old closed jobs; they must load and pass
        # validate_data's archived-job checks.
        call_command('loaddata', FIXTURE, verbosity=0)
        if not Job.objects.filter(status=Job.STATUS_ARCHIVED).exists():
            # The rule is time-based and the spine is the newest cards, so a
            # regenerated fixture may legitimately hold no archive.
            self.skipTest('no archived jobs at this clock')
        out = StringIO()
        call_command('validate_data', stdout=out)
        for line in out.getvalue().splitlines():
            if '[ERROR]' in line:
                self.assertNotIn('archived job', line.lower(), line)

    def test_validate_data_runs_on_fixture(self):
        # The validate_data command must run to completion against the
        # generated fixture (it reports issues, it does not raise on them) —
        # this exercises every check_* method against real converter output.
        call_command('loaddata', FIXTURE, verbosity=0)
        out = StringIO()
        call_command('validate_data', stdout=out)
        # It always prints an error summary line ('N error(s)' or 'No errors').
        self.assertIn('error', out.getvalue().lower())

    def test_bleps_and_shifts_loaded_and_invariants_hold(self):
        # Bleps + Shifts are present, and the time-tracking invariants
        # (enclosure / no per-user overlap / task-not-pending) report no errors.
        from apps.jobs.models import Blep
        from apps.core.models import Shift
        call_command('loaddata', FIXTURE, verbosity=0)
        self.assertGreater(Blep.objects.count(), 0)
        self.assertGreater(Shift.objects.count(), 0)
        out = StringIO()
        call_command('validate_data', stdout=out)
        text = out.getvalue()
        for marker in ('not enclosed by any shift', 'overlaps blep',
                       'is pending but has a blep'):
            self.assertNotIn(marker, text, f'validate_data reported: {marker}')
