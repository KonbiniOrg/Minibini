"""
TDD tests for `work_declined` on EstimateLineItem — the acceptance
checklist's "no work needed" mark (docs/plans/2026-08-15-estimating-structure.md,
"The timeline" / "Accept").

Reversible, PATCH-able ONLY on an ACCEPTED estimate's plain hand lines
(no sources, not an adjustment, not a deposit line, no catalog identity).
Draft and open both refuse the flag.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.estimates.services import EstimateService
from apps.inventory.models import InventoryItem
from apps.jobs.models import Job, RateScheme, Task
from tests.base import grant_atoms


class WorkDeclinedSetup(TestCase):
    """Shared object graph — built directly (no fixtures), mirroring
    tests/test_hand_line_ac_validation.py."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(
            name='Labor', code='WD-LAB', is_active=True,
        )
        self.deposit_cat = AccountingCategory.objects.create(
            name='Deposit', code='WD-DEP', is_active=True,
            taxable=False, is_deposit=True,
        )
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='jd@wd.test', mobile_number='555-0100',
        )
        self.job = Job.objects.create(
            contact=self.contact, job_number='JOB-WD-0001', status=Job.STATUS_APPROVED,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-WD-0001', status=Estimate.STATUS_DRAFT,
        )
        self.hand_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Plain hand line',
            qty=Decimal('1'), price=Decimal('10.00'), accounting_category=self.cat,
        )

    def _accept(self):
        """Bypass Estimate.save()'s transition enforcement (draft can only
        go to open) the same way test_hand_line_ac_validation.py does, by
        writing status via queryset.update()."""
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_ACCEPTED)
        self.estimate.refresh_from_db()

    def _open(self):
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_OPEN)
        self.estimate.refresh_from_db()


class WorkDeclinedFieldDefaultTest(WorkDeclinedSetup):
    def test_default_is_false(self):
        self.assertFalse(self.hand_line.work_declined)
        self.hand_line.refresh_from_db()
        self.assertFalse(self.hand_line.work_declined)


class WorkDeclinedServiceLevelTest(WorkDeclinedSetup):
    """Direct EstimateService.update_line_item() coverage — the plumbing
    the PATCH view delegates to."""

    def test_decline_on_accepted_plain_hand_line_persists(self):
        self._accept()
        updated = EstimateService.update_line_item(
            self.hand_line.pk, work_declined=True,
        )
        self.assertTrue(updated.work_declined)
        self.hand_line.refresh_from_db()
        self.assertTrue(self.hand_line.work_declined)

    def test_undecline_reverses(self):
        self._accept()
        EstimateService.update_line_item(self.hand_line.pk, work_declined=True)
        updated = EstimateService.update_line_item(
            self.hand_line.pk, work_declined=False,
        )
        self.assertFalse(updated.work_declined)

    def test_refused_on_draft(self):
        with self.assertRaises(ValidationError):
            EstimateService.update_line_item(self.hand_line.pk, work_declined=True)
        self.hand_line.refresh_from_db()
        self.assertFalse(self.hand_line.work_declined)

    def test_refused_on_open(self):
        self._open()
        with self.assertRaises(ValidationError):
            EstimateService.update_line_item(self.hand_line.pk, work_declined=True)
        self.hand_line.refresh_from_db()
        self.assertFalse(self.hand_line.work_declined)

    def test_refused_when_mixed_with_other_fields_on_accepted(self):
        self._accept()
        with self.assertRaises(ValidationError):
            EstimateService.update_line_item(
                self.hand_line.pk, work_declined=True, description='changed',
            )
        self.hand_line.refresh_from_db()
        self.assertFalse(self.hand_line.work_declined)
        self.assertEqual(self.hand_line.description, 'Plain hand line')

    def test_refused_when_line_has_sources(self):
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task(job=self.job, name='Setup', est_qty=Decimal('2'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        sourced_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Sourced',
            qty=Decimal('2'), price=Decimal('200.00'),
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=sourced_line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self._accept()
        with self.assertRaises(ValidationError):
            EstimateService.update_line_item(sourced_line.pk, work_declined=True)

    def test_refused_for_adjustment_line(self):
        adj_scheme = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.cat,
        )
        adj_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'),
            adjustment_service=adj_scheme, adjustment_percent=adj_scheme.rate,
        )
        self._accept()
        with self.assertRaises(ValidationError):
            EstimateService.update_line_item(adj_line.pk, work_declined=True)

    def test_refused_for_deposit_line(self):
        deposit_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Deposit',
            qty=Decimal('1'), price=Decimal('500.00'),
            accounting_category=self.deposit_cat,
        )
        self._accept()
        with self.assertRaises(ValidationError):
            EstimateService.update_line_item(deposit_line.pk, work_declined=True)

    def test_refused_for_inventory_item_line(self):
        item = InventoryItem.objects.create(
            code='WD-ITEM-1', accounting_category=self.cat,
            selling_price=Decimal('20.00'),
        )
        catalog_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Catalog pick',
            qty=Decimal('1'), price=Decimal('20.00'),
            accounting_category=self.cat, inventory_item=item,
        )
        self._accept()
        with self.assertRaises(ValidationError):
            EstimateService.update_line_item(catalog_line.pk, work_declined=True)


class WorkDeclinedAPITest(WorkDeclinedSetup):
    """PATCH /api/estimates/{id}/line-items/{item_id}/ — permission +
    HTTP-shape coverage."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.manager = User.objects.create_user(username='wd_mgr', password='x')
        self.manager = grant_atoms(self.manager, 'can_manage_jobs')
        self.plain_user = User.objects.create_user(username='wd_plain', password='x')

    def _url(self):
        return f'/api/estimates/{self.estimate.pk}/line-items/{self.hand_line.pk}/'

    def test_patch_declined_true_on_accepted_returns_200_and_persists(self):
        self._accept()
        self.client.force_authenticate(user=self.manager)
        resp = self.client.patch(self._url(), {'work_declined': True}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['work_declined'])
        self.hand_line.refresh_from_db()
        self.assertTrue(self.hand_line.work_declined)

    def test_patch_declined_true_on_draft_is_refused(self):
        self.client.force_authenticate(user=self.manager)
        resp = self.client.patch(self._url(), {'work_declined': True}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('detail', resp.data)

    def test_patch_declined_true_on_open_is_refused(self):
        self._open()
        self.client.force_authenticate(user=self.manager)
        resp = self.client.patch(self._url(), {'work_declined': True}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('detail', resp.data)

    def test_patch_declined_on_catalog_identity_line_returns_400_detail(self):
        item = InventoryItem.objects.create(
            code='WD-ITEM-API-1', accounting_category=self.cat,
            selling_price=Decimal('20.00'),
        )
        catalog_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Catalog pick',
            qty=Decimal('1'), price=Decimal('20.00'),
            accounting_category=self.cat, inventory_item=item,
        )
        self._accept()
        self.client.force_authenticate(user=self.manager)
        url = f'/api/estimates/{self.estimate.pk}/line-items/{catalog_line.pk}/'
        resp = self.client.patch(url, {'work_declined': True}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('detail', resp.data)

    def test_undecline_via_api(self):
        self._accept()
        self.client.force_authenticate(user=self.manager)
        self.client.patch(self._url(), {'work_declined': True}, format='json')
        resp = self.client.patch(self._url(), {'work_declined': False}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data['work_declined'])

    def test_non_manager_gets_403(self):
        self._accept()
        self.client.force_authenticate(user=self.plain_user)
        resp = self.client.patch(self._url(), {'work_declined': True}, format='json')
        self.assertEqual(resp.status_code, 403, resp.data)
