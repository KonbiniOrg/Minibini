"""Task 7 (task-owned-money Phase 1): RateScheme API — retire/reactivate
endpoints, the include_inactive/task_applicable list filters (filter
composition itself lives in tests/test_service_item_api.py), and the
default_rate_scheme Configuration key's round-trip through /api/settings/.

Supersede is gone: no POST .../supersede/ endpoint, no replaced_by/
replaced_at/superseded fields. See tests/test_rate_scheme_retire.py for the
service-layer (ConfigurationService) coverage of retire/reactivate/delete.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from tests.base import grant_atoms
from apps.core.models import AccountingCategory, Configuration, User
from apps.core.services import ConfigurationService
from apps.jobs.models import RateScheme


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class RateSchemeRetireEndpointTest(TestCase):
    def setUp(self):
        self.admin = grant_atoms(
            User.objects.create_user(username='rsr_admin', password='x'),
            'can_manage_config')
        self.ac = AccountingCategory.objects.create(code='RSR', name='RSR')
        self.scheme = RateScheme.objects.create(
            name='S-rsr', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.ac,
        )

    def test_retire_flips_flag(self):
        resp = _client(self.admin).post(
            f'/api/rate-schemes/{self.scheme.pk}/retire/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('message', resp.data)
        self.scheme.refresh_from_db()
        self.assertFalse(self.scheme.is_active)

    def test_retired_scheme_drops_from_default_list(self):
        _client(self.admin).post(f'/api/rate-schemes/{self.scheme.pk}/retire/')
        resp = _client(self.admin).get('/api/rate-schemes/')
        ids = [r['rate_scheme_id'] for r in resp.json()['results']]
        self.assertNotIn(self.scheme.pk, ids)

    def test_retired_scheme_drops_from_task_applicable(self):
        _client(self.admin).post(f'/api/rate-schemes/{self.scheme.pk}/retire/')
        resp = _client(self.admin).get('/api/rate-schemes/?task_applicable=true')
        ids = [r['rate_scheme_id'] for r in resp.json()['results']]
        self.assertNotIn(self.scheme.pk, ids)

    def test_retire_requires_can_manage_config(self):
        plain = User.objects.create_user(username='rsr_plain', password='x')
        resp = _client(plain).post(f'/api/rate-schemes/{self.scheme.pk}/retire/')
        self.assertEqual(resp.status_code, 403)
        self.scheme.refresh_from_db()
        self.assertTrue(self.scheme.is_active)

    def test_retire_unknown_scheme_404(self):
        resp = _client(self.admin).post('/api/rate-schemes/999999/retire/')
        self.assertEqual(resp.status_code, 404)


class RateSchemeReactivateEndpointTest(TestCase):
    def setUp(self):
        self.admin = grant_atoms(
            User.objects.create_user(username='rsa_admin', password='x'),
            'can_manage_config')
        self.ac = AccountingCategory.objects.create(code='RSA', name='RSA')
        self.scheme = RateScheme.objects.create(
            name='S-rsa', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.ac,
        )
        ConfigurationService.retire_rate_scheme(self.scheme.pk)

    def test_reactivate_flips_flag_back(self):
        resp = _client(self.admin).post(
            f'/api/rate-schemes/{self.scheme.pk}/reactivate/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('message', resp.data)
        self.scheme.refresh_from_db()
        self.assertTrue(self.scheme.is_active)

    def test_reactivated_scheme_returns_to_default_list(self):
        _client(self.admin).post(f'/api/rate-schemes/{self.scheme.pk}/reactivate/')
        resp = _client(self.admin).get('/api/rate-schemes/')
        ids = [r['rate_scheme_id'] for r in resp.json()['results']]
        self.assertIn(self.scheme.pk, ids)

    def test_reactivate_requires_can_manage_config(self):
        plain = User.objects.create_user(username='rsa_plain', password='x')
        resp = _client(plain).post(
            f'/api/rate-schemes/{self.scheme.pk}/reactivate/')
        self.assertEqual(resp.status_code, 403)
        self.scheme.refresh_from_db()
        self.assertFalse(self.scheme.is_active)


class RateSchemeSupersedeRemovedFromApiTest(TestCase):
    def setUp(self):
        self.admin = grant_atoms(
            User.objects.create_user(username='rsp_admin', password='x'),
            'can_manage_config')
        self.ac = AccountingCategory.objects.create(code='RSP', name='RSP')
        self.scheme = RateScheme.objects.create(
            name='S-rsp', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.ac,
        )

    def test_supersede_endpoint_is_gone(self):
        resp = _client(self.admin).post(
            f'/api/rate-schemes/{self.scheme.pk}/supersede/', {}, format='json')
        self.assertEqual(resp.status_code, 404)


class DefaultRateSchemeSettingsTest(TestCase):
    """default_rate_scheme readable/writable via /api/settings/
    (CanManageConfig), following the existing settings-endpoint pattern
    (e.g. default_material_accounting_category)."""

    def setUp(self):
        self.admin = grant_atoms(
            User.objects.create_user(username='drs_admin', password='x'),
            'can_manage_config')
        self.ac = AccountingCategory.objects.create(code='DRS', name='DRS')
        self.scheme = RateScheme.objects.create(
            name='S-drs', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.ac,
        )

    def test_default_rate_scheme_round_trips_through_settings(self):
        resp = _client(self.admin).patch(
            '/api/settings/', {'default_rate_scheme': str(self.scheme.pk)},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['default_rate_scheme'], str(self.scheme.pk))

        resp = _client(self.admin).get('/api/settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['default_rate_scheme'], str(self.scheme.pk))

    def test_default_rate_scheme_requires_can_manage_config(self):
        plain = User.objects.create_user(username='drs_plain', password='x')
        resp = _client(plain).patch(
            '/api/settings/', {'default_rate_scheme': str(self.scheme.pk)},
            format='json')
        self.assertEqual(resp.status_code, 403)

    def test_default_rate_scheme_rejects_unknown_id(self):
        resp = _client(self.admin).patch(
            '/api/settings/', {'default_rate_scheme': '999999'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('default_rate_scheme', resp.data)

    def test_default_rate_scheme_rejects_inactive_scheme(self):
        ConfigurationService.retire_rate_scheme(self.scheme.pk)
        resp = _client(self.admin).patch(
            '/api/settings/', {'default_rate_scheme': str(self.scheme.pk)},
            format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('default_rate_scheme', resp.data)

    def test_default_rate_scheme_rejects_percentage_scheme(self):
        """A percentage scheme is a document-level adjustment, never valid
        task billing (stamp_from_scheme/RateScheme-on-Task guards forbid
        it elsewhere) — default_rate_scheme offers a preset for new task
        creation, so it must reject one too."""
        pct = RateScheme.objects.create(
            name='S-drs-pct', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.ac,
        )
        resp = _client(self.admin).patch(
            '/api/settings/', {'default_rate_scheme': str(pct.pk)},
            format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('default_rate_scheme', resp.data)

    def test_default_rate_scheme_can_be_cleared_to_blank(self):
        Configuration.objects.update_or_create(
            key='default_rate_scheme', defaults={'value': str(self.scheme.pk)})
        resp = _client(self.admin).patch(
            '/api/settings/', {'default_rate_scheme': ''}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['default_rate_scheme'], '')


class RetireDefaultRateSchemeGuardTest(TestCase):
    """RM browser-testing fix: retiring the scheme that is the current
    default_rate_scheme must be REJECTED, not silently clear the key — an
    inactive preset used to be able to linger as the default with no signal
    to the user (task-owned-money Phase 1, Task 7 originally auto-cleared
    the key on retire; RM found that gave no warning at all). REWRITTEN
    from the old RetireClearsDefaultRateSchemeTest, which asserted the
    clear-on-retire behavior this fix replaces."""

    def setUp(self):
        self.admin = grant_atoms(
            User.objects.create_user(username='rcd_admin', password='x'),
            'can_manage_config')
        self.ac = AccountingCategory.objects.create(code='RCD', name='RCD')
        self.scheme = RateScheme.objects.create(
            name='S-rcd', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.ac,
        )
        self.other = RateScheme.objects.create(
            name='S-rcd-other', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('20'), unit_label='ea', accounting_category=self.ac,
        )

    def test_retiring_the_default_is_rejected_via_service(self):
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        with self.assertRaises(ValidationError):
            ConfigurationService.retire_rate_scheme(self.scheme.pk)
        self.scheme.refresh_from_db()
        self.assertTrue(self.scheme.is_active)
        self.assertEqual(
            Configuration.objects.get(key='default_rate_scheme').value,
            str(self.scheme.pk))

    def test_retiring_the_default_is_rejected_via_api(self):
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        resp = _client(self.admin).post(
            f'/api/rate-schemes/{self.scheme.pk}/retire/')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('change the default first', resp.data['detail'])
        self.scheme.refresh_from_db()
        self.assertTrue(self.scheme.is_active)
        self.assertEqual(
            Configuration.objects.get(key='default_rate_scheme').value,
            str(self.scheme.pk))

    def test_deleting_the_default_is_rejected_via_api(self):
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        resp = _client(self.admin).delete(
            f'/api/rate-schemes/{self.scheme.pk}/')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('change the default first', resp.data['detail'])
        self.assertTrue(RateScheme.objects.filter(pk=self.scheme.pk).exists())

    def test_retiring_a_non_default_scheme_still_succeeds(self):
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        ConfigurationService.retire_rate_scheme(self.other.pk)
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_active)
        self.assertEqual(
            Configuration.objects.get(key='default_rate_scheme').value,
            str(self.scheme.pk))

    def test_retiring_when_no_default_is_set_still_succeeds(self):
        ConfigurationService.retire_rate_scheme(self.scheme.pk)
        self.scheme.refresh_from_db()
        self.assertFalse(self.scheme.is_active)

    def test_changing_the_default_away_then_retiring_the_old_default_succeeds(self):
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        ConfigurationService.set('default_rate_scheme', str(self.other.pk))
        ConfigurationService.retire_rate_scheme(self.scheme.pk)
        self.scheme.refresh_from_db()
        self.assertFalse(self.scheme.is_active)


class GenericUpdateIsActiveGuardTest(TestCase):
    """Code review finding (post-implementation, task-owned-money Phase 1):
    RateSchemeSerializer exposes is_active as a normal writable field, and
    the generic PATCH path (RateSchemeViewSet.update ->
    ConfigurationService.update_rate_scheme) did a plain setattr/save with
    no default-scheme check at all. So PATCH /api/rate-schemes/{id}/
    {"is_active": false} could flip the flag without going through
    retire_rate_scheme, leaving default_rate_scheme pointing at a
    now-inactive scheme. update_rate_scheme now shares the same
    reject-if-default guard retire_rate_scheme uses whenever is_active
    transitions True -> False, regardless of entry point. REWRITTEN from
    GenericUpdateIsActiveBypassTest (asserted the old clear-the-key
    behavior; now asserts rejection)."""

    def setUp(self):
        self.admin = grant_atoms(
            User.objects.create_user(username='biv_admin', password='x'),
            'can_manage_config')
        self.ac = AccountingCategory.objects.create(code='BIV', name='BIV')
        self.scheme = RateScheme.objects.create(
            name='S-biv', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.ac,
        )

    def test_patch_is_active_false_on_the_default_is_rejected_via_api(self):
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        resp = _client(self.admin).patch(
            f'/api/rate-schemes/{self.scheme.pk}/',
            {'is_active': False}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('change the default first', resp.data['detail'])
        self.scheme.refresh_from_db()
        self.assertTrue(self.scheme.is_active)
        self.assertEqual(
            Configuration.objects.get(key='default_rate_scheme').value,
            str(self.scheme.pk))

    def test_update_rate_scheme_service_rejects_deactivating_the_default(self):
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        with self.assertRaises(ValidationError):
            ConfigurationService.update_rate_scheme(self.scheme, is_active=False)
        self.scheme.refresh_from_db()
        self.assertTrue(self.scheme.is_active)

    def test_update_rate_scheme_service_leaves_default_alone_when_is_active_untouched(self):
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        ConfigurationService.update_rate_scheme(self.scheme, rate=Decimal('55'))
        self.assertEqual(
            Configuration.objects.get(key='default_rate_scheme').value,
            str(self.scheme.pk))

    def test_update_rate_scheme_service_reactivating_after_guard_rejection_is_unaffected(self):
        # The rejected deactivate attempt must not have partially applied.
        ConfigurationService.set('default_rate_scheme', str(self.scheme.pk))
        with self.assertRaises(ValidationError):
            ConfigurationService.update_rate_scheme(self.scheme, is_active=False)
        ConfigurationService.update_rate_scheme(self.scheme, rate=Decimal('12'))
        self.scheme.refresh_from_db()
        self.assertTrue(self.scheme.is_active)
        self.assertEqual(self.scheme.rate, Decimal('12'))
