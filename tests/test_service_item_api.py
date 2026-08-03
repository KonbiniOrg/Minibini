from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.jobs.models import RateScheme
from tests.base import BaseTestCase

User = get_user_model()

class RateSchemeAPITest(TestCase):
    def setUp(self):
        from apps.core.models import AccountingCategory
        self.admin = User.objects.create_user(username='admin', password='testpass', is_staff=True)
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_config')
        self.admin.user_permissions.add(perm)
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.ac = AccountingCategory.objects.create(code='LAB', name='Labor')
        self.scheme = RateScheme.objects.create(
            name='Hourly Labor', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'), unit_label='hour',
            accounting_category=self.ac,
        )

    def test_list_requires_auth(self):
        resp = self.client.get('/api/rate-schemes/')
        self.assertEqual(resp.status_code, 403)

    def test_list_authenticated(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.get('/api/rate-schemes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 1)

    def test_create_requires_config_perm(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'New Scheme', 'algorithm': 'entered_qty',
            'rate': '50.00', 'unit_label': 'ea',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_create_with_config_perm(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'CNC Setup', 'algorithm': 'entered_qty',
            'rate': '50.00', 'unit_label': 'ea',
            'accounting_category': self.ac.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['name'], 'CNC Setup')

    def test_create_with_modifiers(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'CNC Router', 'algorithm': 'entered_qty',
            'rate': '4.00', 'unit_label': 'min',
            'modifiers': [{'key': 'messy', 'label': 'Messy', 'percent': 10}],
            'accounting_category': self.ac.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.json()['modifiers']), 1)

    def test_create_percentage_without_unit_label_defaults_none(self):
        """A percentage service carries no unit; omitting unit_label is fine and
        it defaults to 'none' (the percentage form hides the unit field)."""
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'Rush Fee', 'algorithm': 'percentage',
            'rate': '15.00',
            'accounting_category': self.ac.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['unit_label'], 'none')

    def test_create_percentage_blank_unit_label_ok(self):
        """A blank unit_label (what the percentage form submits) is accepted."""
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'Loyalty Discount', 'algorithm': 'percentage',
            'rate': '-10.00', 'unit_label': '',
            'accounting_category': self.ac.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['unit_label'], 'none')

    def test_create_non_percentage_still_requires_unit_label(self):
        """Non-percentage algorithms still require a configured unit_label."""
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'No Unit Flat', 'algorithm': 'entered_qty',
            'rate': '50.00',
            'accounting_category': self.ac.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('unit_label', resp.json())

    def test_update(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.patch(
            f'/api/rate-schemes/{self.scheme.pk}/',
            {'rate': '50.00'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['rate'], '50.00')

    def test_delete(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.delete(f'/api/rate-schemes/{self.scheme.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(RateScheme.objects.filter(pk=self.scheme.pk).exists())

    def test_retrieve(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.get(f'/api/rate-schemes/{self.scheme.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Hourly Labor')


class RateSchemeReferencedEditTest(BaseTestCase):
    """Task 4 (task-owned-money Phase 1): presets are freely editable — a
    stamped Task already owns a permanent copy of the money fields, so
    editing (or PUTting) a referenced preset via the API succeeds instead of
    the old 409-with-supersede_url response. Task 7 removes that shaping
    from the view entirely."""
    fixtures = []

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission
        self.user = User.objects.create_user('admin-edit', 'admin-edit@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_config')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)

    def _make_referenced_scheme(self):
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Task, Job
        from apps.contacts.models import Contact, Business
        # Real schema requires Business.business_name + default_contact FK,
        # and Contact.email. Build pair: Contact first, then Business with
        # default_contact, then attach business back to contact and save.
        ac = AccountingCategory.objects.create(code='X-eb', name='X-eb')
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-eb@l.test',
        )
        biz = Business.objects.create(
            business_name='B-eb', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J-eb', contact=contact)
        s = RateScheme.objects.create(
            name='S-eb', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        Task.objects.create(job=job, name='t', source_scheme=s)
        return s

    def test_patch_referenced_scheme_succeeds(self):
        s = self._make_referenced_scheme()
        resp = self.client.patch(
            f'/api/rate-schemes/{s.pk}/',
            {'rate': '99'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['rate'], '99.00')
        s.refresh_from_db()
        self.assertEqual(s.rate, Decimal('99.00'))

    def test_put_referenced_scheme_succeeds(self):
        # Verify the same behavior on PUT (full update), not just PATCH.
        from apps.core.models import AccountingCategory
        s = self._make_referenced_scheme()
        ac = AccountingCategory.objects.get(code='X-eb')
        resp = self.client.put(
            f'/api/rate-schemes/{s.pk}/',
            {
                'name': 'S-eb-changed', 'algorithm': 'entered_qty',
                'rate': '99', 'unit_label': 'ea',
                'accounting_category': ac.pk,
                'modifiers': [], 'description': '',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['name'], 'S-eb-changed')

    def test_patch_unreferenced_scheme_succeeds(self):
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme
        ac = AccountingCategory.objects.create(code='X-ok', name='X-ok')
        s = RateScheme.objects.create(
            name='S-ok', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        resp = self.client.patch(
            f'/api/rate-schemes/{s.pk}/',
            {'rate': '2'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)


class RateSchemeIncludeInactiveFilterTest(BaseTestCase):
    """GET /api/rate-schemes/?include_inactive=true — the retirement-era
    replacement for the old include_superseded/only_superseded filters."""
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        from apps.jobs.models import RateScheme
        self.user = User.objects.create_user('u-lf', 'u-lf@x.test', 'pw')
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='Z-lf', name='Z-lf')
        self.active = RateScheme.objects.create(
            name='A-lf', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.retired = RateScheme.objects.create(
            name='O-lf', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.retired.is_active = False
        self.retired.save()

    def test_default_list_excludes_inactive(self):
        resp = self.client.get('/api/rate-schemes/')
        body = resp.json()
        items = body.get('results', body)
        ids = [r['rate_scheme_id'] for r in items]
        self.assertIn(self.active.pk, ids)
        self.assertNotIn(self.retired.pk, ids)

    def test_include_inactive_returns_all(self):
        resp = self.client.get('/api/rate-schemes/?include_inactive=true')
        body = resp.json()
        items = body.get('results', body)
        ids = [r['rate_scheme_id'] for r in items]
        self.assertIn(self.active.pk, ids)
        self.assertIn(self.retired.pk, ids)


class RateSchemeSerializerExtraFieldsTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        from apps.jobs.models import RateScheme
        self.user = User.objects.create_user('u-sef', 'u-sef@x.test', 'pw')
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='X-sef', name='X-sef')
        self.s = RateScheme.objects.create(
            name='S-sef', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )

    def test_serializer_exposes_is_active_and_counts_no_supersession_fields(self):
        resp = self.client.get(f'/api/rate-schemes/{self.s.pk}/')
        body = resp.json()
        self.assertIn('is_active', body)
        self.assertTrue(body['is_active'])
        self.assertNotIn('replaced_by', body)
        self.assertNotIn('replaced_at', body)
        self.assertNotIn('superseded', body)
        self.assertIn('reference_counts', body)
        self.assertEqual(body['reference_counts']['task_count'], 0)
        self.assertEqual(body['reference_counts']['service_item_count'], 0)

    def test_unit_label_must_be_in_configured_units(self):
        from apps.core.models import User
        from django.contrib.auth.models import Permission
        admin = User.objects.create_user('a-sef', 'a-sef@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_config')
        admin.user_permissions.add(perm)
        self.client.force_login(admin)
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'BadUnits', 'algorithm': 'entered_qty', 'rate': '1',
            'unit_label': 'frobnitz-not-a-unit',
            'accounting_category': self.ac.pk,
            'modifiers': [], 'description': '',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn('unit_label', body)


class RateSchemeSerializerElapsedUnitTest(TestCase):
    """Time-based (elapsed_time) schemes are always billed in hours; the
    serializer overrides any submitted unit_label rather than validating it."""

    def setUp(self):
        from apps.core.models import AccountingCategory
        self.category = AccountingCategory.objects.create(
            code='EL-sef', name='Elapsed')

    def test_serializer_forces_hour_on_elapsed(self):
        from apps.api.rate_schemes.serializers import RateSchemeSerializer
        data = {'name': 'Shop time', 'algorithm': 'elapsed_time',
                'rate': '90.00', 'unit_label': 'gal',
                'accounting_category': self.category.pk}
        ser = RateSchemeSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data['unit_label'], 'hour')


class RateSchemeTaskApplicableFilterTest(TestCase):
    """GET /api/rate-schemes/?task_applicable=true must exclude percentage
    services AND inactive presets — a task-creation picker should never
    offer either."""

    def setUp(self):
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme
        self.user = get_user_model().objects.create_user(
            username='u-taf', password='testpass',
        )
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='TAF', name='TAF')
        self.hourly = RateScheme.objects.create(
            name='Hourly TAF', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'), unit_label='hour', accounting_category=self.ac,
        )
        RateScheme.objects.create(
            name='Rush TAF', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15'), unit_label='%', accounting_category=self.ac,
        )
        self.retired = RateScheme.objects.create(
            name='Retired TAF', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('30'), unit_label='ea', accounting_category=self.ac,
        )
        self.retired.is_active = False
        self.retired.save()

    def test_task_applicable_filter_excludes_percentage(self):
        resp = self.client.get('/api/rate-schemes/?task_applicable=true')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        items = body.get('results', body)
        algos = {r['algorithm'] for r in items}
        self.assertNotIn('percentage', algos)

    def test_task_applicable_filter_excludes_inactive(self):
        resp = self.client.get('/api/rate-schemes/?task_applicable=true')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        items = body.get('results', body)
        ids = [r['rate_scheme_id'] for r in items]
        self.assertIn(self.hourly.pk, ids)
        self.assertNotIn(self.retired.pk, ids)

    def test_task_applicable_filter_includes_inactive_when_combined_with_include_inactive(self):
        # task_applicable's own is_active=True filter wins regardless —
        # a task-creation picker must never offer an inactive preset even
        # if the caller also asked to include inactive schemes.
        resp = self.client.get(
            '/api/rate-schemes/?task_applicable=true&include_inactive=true')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        items = body.get('results', body)
        ids = [r['rate_scheme_id'] for r in items]
        self.assertNotIn(self.retired.pk, ids)


class RateSchemeSearchFilterTest(TestCase):
    """GET /api/rate-schemes/?search= must filter by name or description."""

    def setUp(self):
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme
        self.user = get_user_model().objects.create_user(
            username='u-srch', password='testpass',
        )
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='SRCH', name='SRCH')
        self.cnc = RateScheme.objects.create(
            name='CNC Routing', description='Router pass on CNC bed',
            algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('75.00'),
            unit_label='hour', accounting_category=self.ac,
        )
        self.design = RateScheme.objects.create(
            name='Design Fee', description='Graphic design work',
            algorithm=RateScheme.ENTERED_QTY, rate=Decimal('150.00'),
            unit_label='ea', accounting_category=self.ac,
        )

    def _ids(self, resp):
        body = resp.json()
        items = body.get('results', body)
        return [r['rate_scheme_id'] for r in items]

    def test_search_by_name_returns_match(self):
        resp = self.client.get('/api/rate-schemes/?search=CNC')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertIn(self.cnc.pk, ids)
        self.assertNotIn(self.design.pk, ids)

    def test_search_no_match_excludes_item(self):
        resp = self.client.get('/api/rate-schemes/?search=xyznonexistent')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertNotIn(self.cnc.pk, ids)
        self.assertNotIn(self.design.pk, ids)

    def test_search_by_description(self):
        resp = self.client.get('/api/rate-schemes/?search=Graphic')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertIn(self.design.pk, ids)
        self.assertNotIn(self.cnc.pk, ids)
