"""C-group config CRUD extraction (2026-07-04).

RateScheme CRUD folds into ConfigurationService alongside the
AccountingCategory methods — the referenced-freeze decision moves out of the
viewset into the service, and the viewset only translates it to the 409
payload. AccountingCategory gains the missing delete guard: a
PROTECT-referenced category deletes as a friendly 409, not a ProtectedError
500.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from tests.base import grant_atoms
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.core.services import ConfigurationService
from apps.jobs.models import Job, RateScheme, Task


def _admin_client():
    admin = grant_atoms(
        User.objects.create_user(username='cfg_admin', password='x'),
        'can_manage_config')
    c = APIClient()
    c.force_authenticate(user=admin)
    return c


class RateSchemeServiceCrudTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='cfg', code='CFG')

    def _scheme(self, name='S-cfg'):
        return ConfigurationService.create_rate_scheme(
            name=name, algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea',
            accounting_category=self.cat)

    def _reference(self, scheme):
        contact = Contact.objects.create(first_name='C', last_name='F')
        job = Job.objects.create(job_number='JOB-CFG-1', contact=contact)
        Task.objects.create(job=job, name='t', rate_scheme=scheme)

    def test_create_and_update_unreferenced(self):
        scheme = self._scheme()
        self.assertIsNotNone(scheme.pk)
        ConfigurationService.update_rate_scheme(scheme, rate=Decimal('12'))
        scheme.refresh_from_db()
        self.assertEqual(scheme.rate, Decimal('12'))

    def test_update_referenced_scheme_refused(self):
        scheme = self._scheme()
        self._reference(scheme)
        with self.assertRaises(ValidationError) as ctx:
            ConfigurationService.update_rate_scheme(scheme, rate=Decimal('99'))
        self.assertEqual(ctx.exception.code, 'referenced')
        scheme.refresh_from_db()
        self.assertEqual(scheme.rate, Decimal('10'))

    def test_delete_referenced_scheme_refused(self):
        scheme = self._scheme()
        self._reference(scheme)
        with self.assertRaises(ValidationError) as ctx:
            ConfigurationService.delete_rate_scheme(scheme)
        self.assertEqual(ctx.exception.code, 'referenced')
        self.assertTrue(RateScheme.objects.filter(pk=scheme.pk).exists())

    def test_delete_unreferenced_scheme(self):
        scheme = self._scheme()
        ConfigurationService.delete_rate_scheme(scheme)
        self.assertFalse(RateScheme.objects.filter(pk=scheme.pk).exists())

    def test_api_referenced_patch_still_409_with_payload(self):
        # The 409 shape (supersede_url + reference_counts) is the SPA's
        # contract; the decision now lives in the service.
        scheme = self._scheme()
        self._reference(scheme)
        resp = _admin_client().patch(
            f'/api/rate-schemes/{scheme.pk}/', {'rate': '99'}, format='json')
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertIn('supersede_url', resp.data)
        self.assertIn('reference_counts', resp.data)


class AccountingCategoryDeleteGuardTest(TestCase):
    def setUp(self):
        self.client_ = _admin_client()

    def test_referenced_category_delete_is_409_not_500(self):
        cat = AccountingCategory.objects.create(name='cfgd', code='CFGD')
        RateScheme.objects.create(
            name='S-cfgd', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=cat)
        resp = self.client_.delete(f'/api/accounting-categories/{cat.pk}/')
        self.assertEqual(resp.status_code, 409, getattr(resp, 'data', None))
        self.assertTrue(AccountingCategory.objects.filter(pk=cat.pk).exists())

    def test_unreferenced_category_deletes(self):
        cat = AccountingCategory.objects.create(name='cfgu', code='CFGU')
        resp = self.client_.delete(f'/api/accounting-categories/{cat.pk}/')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', None))
        self.assertFalse(AccountingCategory.objects.filter(pk=cat.pk).exists())

    def test_adjustment_target_only_category_delete_is_409(self):
        """A category referenced ONLY via adjustment_target_categories (a
        hidden M2M that doesn't PROTECT) must still refuse deletion — the
        ProtectedError-only guard would silently delete it and the through
        row. Mirrors tests.test_deposit_category's adjustment-target setup."""
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate, EstimateLineItem

        cat = AccountingCategory.objects.create(name='cfg-adjtgt', code='CFGADJT')
        other_cat = AccountingCategory.objects.create(name='cfg-adjoth', code='CFGADJO')
        contact = Contact.objects.create(first_name='Cfg', last_name='Adj')
        job = Job.objects.create(job_number='JOB-CFG-ADJ-1', contact=contact)
        est = Estimate.objects.create(
            job=job, estimate_number='EST-CFG-ADJ-1', version=1,
            status=Estimate.STATUS_DRAFT)
        line = EstimateLineItem.objects.create(
            estimate=est, line_number=1,
            qty=Decimal('1'), price=Decimal('0.00'),
            accounting_category=other_cat)
        line.adjustment_target_categories.set([cat.pk])

        resp = self.client_.delete(f'/api/accounting-categories/{cat.pk}/')
        self.assertEqual(resp.status_code, 409, getattr(resp, 'data', None))
        self.assertTrue(AccountingCategory.objects.filter(pk=cat.pk).exists())
        line.refresh_from_db()
        self.assertIn(cat.pk, line.adjustment_target_categories.values_list('pk', flat=True))
