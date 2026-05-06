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
            rate=Decimal('45.00'), unit_label='hours',
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
            'name': 'New Scheme', 'algorithm': 'flat_fee',
            'rate': '50.00', 'unit_label': 'ea',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_create_with_config_perm(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'CNC Setup', 'algorithm': 'flat_fee',
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


class RateSchemeEditBlockTest(BaseTestCase):
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
        from apps.jobs.models import RateScheme, PlanTask, Job
        from apps.estimates.models import EstWorksheet
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
        ws = EstWorksheet.objects.create(job=job)
        s = RateScheme.objects.create(
            name='S-eb', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='t', rate_scheme=s,
            est_qty=Decimal('1'),
        )
        return s

    def test_patch_referenced_scheme_returns_409(self):
        s = self._make_referenced_scheme()
        resp = self.client.patch(
            f'/api/rate-schemes/{s.pk}/',
            {'rate': '99'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertIn('supersede_url', body)
        self.assertIn('reference_counts', body)
        self.assertEqual(body['reference_counts']['plan_task_count'], 1)

    def test_put_referenced_scheme_returns_409(self):
        # Verify the same behavior on PUT (full update), not just PATCH.
        from apps.core.models import AccountingCategory
        s = self._make_referenced_scheme()
        ac = AccountingCategory.objects.get(code='X-eb')
        resp = self.client.put(
            f'/api/rate-schemes/{s.pk}/',
            {
                'name': 'S-eb-changed', 'algorithm': 'flat_fee',
                'rate': '99', 'unit_label': 'ea',
                'accounting_category': ac.pk,
                'modifiers': [], 'description': '',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_patch_unreferenced_scheme_succeeds(self):
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme
        ac = AccountingCategory.objects.create(code='X-ok', name='X-ok')
        s = RateScheme.objects.create(
            name='S-ok', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        resp = self.client.patch(
            f'/api/rate-schemes/{s.pk}/',
            {'rate': '2'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)


class RateSchemeSupersedeEndpointTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        from django.contrib.auth.models import Permission
        self.user = User.objects.create_user('admin-sup', 'admin-sup@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_config')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='Y-sup', name='Y-sup')

    def test_supersede_creates_new_and_links_old(self):
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='O-sup', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        resp = self.client.post(
            f'/api/rate-schemes/{old.pk}/supersede/',
            {
                'name': 'O-sup v2', 'rate': '7', 'algorithm': 'flat_fee',
                'unit_label': 'ea', 'accounting_category': self.ac.pk,
                'modifiers': [], 'description': '',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        new_id = resp.json()['rate_scheme_id']
        old.refresh_from_db()
        self.assertEqual(old.replaced_by_id, new_id)
        self.assertIsNotNone(old.replaced_at)

    def test_supersede_requires_can_manage_config(self):
        from apps.core.models import User
        from apps.jobs.models import RateScheme
        plain = User.objects.create_user('plain-sup', 'plain-sup@x.test', 'pw')
        self.client.force_login(plain)
        old = RateScheme.objects.create(
            name='O-sup-perm', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        resp = self.client.post(f'/api/rate-schemes/{old.pk}/supersede/', {})
        self.assertEqual(resp.status_code, 403)

    def test_supersede_already_superseded_returns_409(self):
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='O-sup-twice', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        # First supersede via the model method
        old.supersede(name='O-sup-twice v2')
        # Second supersede via API should be rejected
        resp = self.client.post(
            f'/api/rate-schemes/{old.pk}/supersede/',
            {
                'name': 'O-sup-twice v3', 'rate': '9', 'algorithm': 'flat_fee',
                'unit_label': 'ea', 'accounting_category': self.ac.pk,
                'modifiers': [], 'description': '',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)


class RateSchemeListFilterTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        from apps.jobs.models import RateScheme
        self.user = User.objects.create_user('u-lf', 'u-lf@x.test', 'pw')
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='Z-lf', name='Z-lf')
        self.active = RateScheme.objects.create(
            name='A-lf', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.old = RateScheme.objects.create(
            name='O-lf', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.new = self.old.supersede(name='N-lf')

    def test_default_list_excludes_superseded(self):
        resp = self.client.get('/api/rate-schemes/')
        body = resp.json()
        items = body.get('results', body)
        ids = [r['rate_scheme_id'] for r in items]
        self.assertIn(self.active.pk, ids)
        self.assertIn(self.new.pk, ids)
        self.assertNotIn(self.old.pk, ids)

    def test_include_superseded_returns_all(self):
        resp = self.client.get('/api/rate-schemes/?include_superseded=true')
        body = resp.json()
        items = body.get('results', body)
        ids = [r['rate_scheme_id'] for r in items]
        self.assertIn(self.old.pk, ids)
        self.assertIn(self.active.pk, ids)
        self.assertIn(self.new.pk, ids)

    def test_only_superseded_returns_just_old(self):
        resp = self.client.get('/api/rate-schemes/?only_superseded=true')
        body = resp.json()
        items = body.get('results', body)
        ids = [r['rate_scheme_id'] for r in items]
        self.assertIn(self.old.pk, ids)
        self.assertNotIn(self.active.pk, ids)
        self.assertNotIn(self.new.pk, ids)


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
            name='S-sef', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )

    def test_serializer_includes_replaced_fields_and_counts(self):
        resp = self.client.get(f'/api/rate-schemes/{self.s.pk}/')
        body = resp.json()
        self.assertIn('replaced_by', body)
        self.assertIn('replaced_at', body)
        self.assertIn('superseded', body)
        self.assertFalse(body['superseded'])
        self.assertIn('reference_counts', body)
        self.assertEqual(body['reference_counts']['plan_task_count'], 0)
        self.assertEqual(body['reference_counts']['task_charge_count'], 0)
        self.assertEqual(body['reference_counts']['task_template_count'], 0)

    def test_unit_label_must_be_in_configured_units(self):
        from apps.core.models import User
        from django.contrib.auth.models import Permission
        admin = User.objects.create_user('a-sef', 'a-sef@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_config')
        admin.user_permissions.add(perm)
        self.client.force_login(admin)
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'BadUnits', 'algorithm': 'flat_fee', 'rate': '1',
            'unit_label': 'frobnitz-not-a-unit',
            'accounting_category': self.ac.pk,
            'modifiers': [], 'description': '',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn('unit_label', body)


class RateSchemeSupersedeSameNameTest(BaseTestCase):
    """
    The SPA always sends a `name` (it's a pre-populated form field).
    When the user leaves it untouched, the payload's name equals the
    old scheme's name — which used to collide on the unique constraint.
    The model rename-old-first algorithm now handles this; verify it
    end-to-end via the API.
    """
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        from django.contrib.auth.models import Permission
        self.user = User.objects.create_user('admin-same', 'admin-same@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_config')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='SN', name='SN')

    def test_supersede_with_same_name_as_old_succeeds(self):
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='SN-Hourly', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        resp = self.client.post(
            f'/api/rate-schemes/{old.pk}/supersede/',
            {
                'name': 'SN-Hourly',  # unchanged from old
                'rate': '7', 'algorithm': 'flat_fee',
                'unit_label': 'ea', 'accounting_category': self.ac.pk,
                'modifiers': [], 'description': '',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['name'], 'SN-Hourly')
        old.refresh_from_db()
        self.assertEqual(old.name, 'SN-Hourly (v1)')
        # Both rows still in the DB, names unique.
        self.assertEqual(
            RateScheme.objects.filter(name='SN-Hourly').count(), 1,
        )
        self.assertEqual(
            RateScheme.objects.filter(name='SN-Hourly (v1)').count(), 1,
        )

    def test_supersede_with_changed_name_still_renames_old(self):
        """Old row gets (v1) regardless of whether the new name was changed."""
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='SN-Setup', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        resp = self.client.post(
            f'/api/rate-schemes/{old.pk}/supersede/',
            {
                'name': 'SN-Setup Premium',
                'rate': '8', 'algorithm': 'flat_fee',
                'unit_label': 'ea', 'accounting_category': self.ac.pk,
                'modifiers': [], 'description': '',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['name'], 'SN-Setup Premium')
        old.refresh_from_db()
        self.assertEqual(old.name, 'SN-Setup (v1)')
