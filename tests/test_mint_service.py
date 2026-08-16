"""MintService: minting a claim (EstimateLineItemSource) that binds a
just-created atom to an estimate line, on ACCEPTED estimates only.

Object graph is built by hand (mirrors tests/test_dead_document_releases_claims.py
and tests/test_hand_line_ac_validation.py) — tests/base.py's BaseTestCase only
loads unit_test_data.json, it has no create_* factory helpers.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource, ServiceItem
from apps.estimates.mint import MINT_STATUSES, MintService
from apps.inventory.models import InventoryItem
from apps.jobs.models import Job, RateScheme, Task


class MintServiceTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        AppState.objects.create(key='estimate_counter', value='0')
        self.cat = AccountingCategory.objects.create(code='LAB', name='Labor')
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001', status=Job.STATUS_APPROVED)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ENTERED_QTY, rate=Decimal('100'),
            unit_label='hour', accounting_category=self.cat)
        self.adj_scheme = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE, rate=Decimal('10'),
            unit_label='%', accounting_category=self.cat)

        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT)
        self.line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Reception desk',
            qty=Decimal('1'), price=Decimal('0.00'), accounting_category=self.cat)
        self.task = self._make_task(self.job, 'CNC parts')

    def _make_task(self, job, name):
        task = Task(job=job, name=name, est_qty=Decimal('1'))
        task.stamp_from_scheme(self.scheme)
        task.save()
        return task

    def _accept(self, estimate=None):
        # QuerySet.update() deliberately bypasses save()'s transition
        # guard and side effects (e.g. release-claims hooks) so we can
        # arrange arbitrary status states directly.
        est = estimate or self.estimate
        Estimate.objects.filter(pk=est.pk).update(status=Estimate.STATUS_ACCEPTED)
        est.refresh_from_db()

    def _open(self, estimate=None):
        est = estimate or self.estimate
        Estimate.objects.filter(pk=est.pk).update(status=Estimate.STATUS_OPEN)
        est.refresh_from_db()

    def _claim(self, line=None, task=None):
        return MintService.claim_atom_for_line(
            line or self.line,
            EstimateLineItemSource.SOURCE_TASK,
            (task or self.task).pk,
        )

    def test_statuses_constant_is_exactly_accepted(self):
        self.assertEqual(MINT_STATUSES, ('accepted',))

    def test_claims_on_accepted(self):
        self._accept()
        src = self._claim()
        self.assertEqual(src.estimate_line_item_id, self.line.pk)
        self.assertEqual(src.source_pk, self.task.pk)

    def test_refuses_draft(self):
        # self.estimate starts in draft (setUp) — no arrangement needed.
        with self.assertRaises(ValidationError):
            self._claim()

    def test_refuses_open(self):
        self._open()
        with self.assertRaises(ValidationError):
            self._claim()

    def test_refuses_dead_statuses(self):
        for status in ('rejected', 'superseded', 'expired'):
            with self.subTest(status=status):
                Estimate.objects.filter(pk=self.estimate.pk).update(status=status)
                self.estimate.refresh_from_db()
                with self.assertRaises(ValidationError):
                    self._claim()

    def test_refuses_adjustment_line(self):
        adj = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=None,
            adjustment_service=self.adj_scheme, adjustment_percent=self.adj_scheme.rate)
        self._accept()
        with self.assertRaises(ValidationError):
            self._claim(line=adj)

    def test_refuses_declined_line(self):
        self._accept()
        self.line.work_declined = True
        self.line.save()
        with self.assertRaises(ValidationError) as ctx:
            self._claim()
        self.assertIn('un-mark it first', str(ctx.exception))

    def test_refuses_service_item_catalog_identity(self):
        service_item = ServiceItem.objects.create(
            template_name='CAM coding', rate_scheme=self.scheme,
            default_active_modifiers=[])
        svc_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='CAM work',
            qty=Decimal('1'), price=Decimal('100'), accounting_category=self.cat,
            service_item=service_item)
        self._accept()
        with self.assertRaises(ValidationError):
            self._claim(line=svc_line)

    def test_refuses_inventory_item_catalog_identity(self):
        item = InventoryItem.objects.create(
            code='MINT-ITEM-1', accounting_category=self.cat,
            selling_price=Decimal('20.00'))
        catalog_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Catalog pick',
            qty=Decimal('1'), price=Decimal('20.00'),
            accounting_category=self.cat, inventory_item=item)
        self._accept()
        with self.assertRaises(ValidationError):
            self._claim(line=catalog_line)

    def test_refuses_is_material_catalog_identity(self):
        material_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Bare material',
            qty=Decimal('1'), price=Decimal('15.00'),
            accounting_category=self.cat, is_material=True)
        self._accept()
        with self.assertRaises(ValidationError):
            self._claim(line=material_line)

    def test_refuses_atom_from_another_job(self):
        other_contact = Contact.objects.create(
            first_name='O', last_name='T', email='o@t.com', mobile_number='555-1')
        other_job = Job.objects.create(
            contact=other_contact, job_number='JOB-2026-0002', status=Job.STATUS_APPROVED)
        stray = self._make_task(other_job, 'stray')
        self._accept()
        with self.assertRaises(ValidationError):
            self._claim(task=stray)

    def test_refuses_already_claimed_atom(self):
        self._accept()
        self._claim()
        with self.assertRaises(ValidationError):
            self._claim()

    def test_refuses_missing_atom(self):
        self._accept()
        with self.assertRaises(ValidationError):
            MintService.claim_atom_for_line(
                self.line, EstimateLineItemSource.SOURCE_TASK, 999999)
