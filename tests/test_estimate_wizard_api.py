from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, User, AppState
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material
from apps.jobs.models import Job, Task, RateScheme


class EstimateWizardAPITest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.user = User.objects.create_user(username='u', password='p')
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)

        self.client = APIClient()
        self.client.login(username='u', password='p')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = Task(
            job=self.job, name='Setup',
            est_qty=Decimal('2'),
        )
        self.pt.stamp_from_scheme(self.scheme)
        self.pt.save()
        self.pm = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number=self.job.job_number, version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def test_source_pool_endpoint(self):
        url = f'/api/estimates/{self.estimate.pk}/source-pool/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('atoms', data)
        types = [a['type'] for a in data['atoms']]
        self.assertIn('task', types)
        self.assertIn('material', types)

    def test_line_items_from_atoms_endpoint(self):
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {'atoms': [{'type': 'task', 'id': self.pt.pk}]}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 1)

    def test_line_items_from_atoms_conflict_returns_409(self):
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {'atoms': [{'type': 'task', 'id': self.pt.pk}]}
        self.client.post(url, payload, format='json')
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['code'], 'atoms_already_claimed')

    def test_line_items_from_atoms_applies_overrides(self):
        """Task 8: bundle-modal overrides body key passes through and wins
        over the derived defaults."""
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {
            'atoms': [{'type': 'task', 'id': self.pt.pk}],
            'overrides': {'description': 'Bundled setup', 'qty': '5',
                          'units': 'ea', 'price': '42.50'},
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['description'], 'Bundled setup')
        self.assertEqual(Decimal(resp.data['qty']), Decimal('5'))
        self.assertEqual(resp.data['units'], 'ea')
        self.assertEqual(Decimal(resp.data['price']), Decimal('42.50'))

    def test_line_items_from_atoms_unknown_override_key_returns_400(self):
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {
            'atoms': [{'type': 'task', 'id': self.pt.pk}],
            'overrides': {'nonsense': 'x'},
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)

    def test_line_items_from_atoms_per_unit_endpoint(self):
        """Task 4: `per_unit:true` passes through the view into the wizard
        service — the created line serializes `per_unit: true`, and the
        stamped atom totals are visible on re-fetch (qty x per-unit value)."""
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {
            'atoms': [{'type': 'task', 'id': self.pt.pk}],
            'overrides': {
                'description': 'Per-unit bundle', 'qty': '10',
                'units': 'each', 'price': '200.00',
            },
            'per_unit': True,
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data['per_unit'])
        self.assertEqual(Decimal(resp.data['qty']), Decimal('10'))
        self.assertEqual(Decimal(resp.data['price']), Decimal('200.00'))

        # The task atom (est_qty=2 pre-bundle) is stamped to the whole-job
        # total for qty=10: 2 * 10 = 20 — visible on re-fetching the atom
        # (the source pool, same as any other estimate-composition write).
        self.pt.refresh_from_db()
        self.assertEqual(self.pt.est_qty, Decimal('20.00'))
        pool_resp = self.client.get(f'/api/estimates/{self.estimate.pk}/source-pool/')
        pooled = next(a for a in pool_resp.json()['atoms'] if a['type'] == 'task' and a['id'] == self.pt.pk)
        self.assertEqual(Decimal(pooled['qty']), Decimal('20.00'))

        # The line's sources list the claim (the pre-multiplication per-unit
        # value snapshots onto the source row, not yet API-exposed).
        list_resp = self.client.get(f'/api/estimates/{self.estimate.pk}/line-items/')
        data = list_resp.json()
        items = data.get('results', data) if isinstance(data, dict) else data
        match = next(i for i in items if i['line_item_id'] == resp.data['line_item_id'])
        self.assertEqual(len(match['sources']), 1)
        from apps.estimates.models import EstimateLineItemSource
        src = EstimateLineItemSource.objects.get(estimate_line_item_id=resp.data['line_item_id'])
        self.assertEqual(src.per_unit_qty, Decimal('2.00'))

    def test_line_items_from_atoms_per_unit_est_qty_none_task_returns_400(self):
        """Final-review Finding 2: a per-unit bundle over a task with
        est_qty=None (legal on the model) must 400 with a plain, user-
        facing sentence — not mint a claim whose per_unit_qty snapshots
        NULL (invisible to the per-unit sum/drift/Revert forever) — and
        must create nothing."""
        unquantified = Task(job=self.job, name='Unquantified')
        unquantified.stamp_from_scheme(self.scheme)
        unquantified.save()
        self.assertIsNone(unquantified.est_qty)

        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {
            'atoms': [{'type': 'task', 'id': unquantified.pk}],
            'overrides': {
                'description': 'No qty yet', 'qty': '5',
                'units': 'each', 'price': '10.00',
            },
            'per_unit': True,
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        detail = resp.json().get('detail', '')
        self.assertIn('has no estimated quantity', detail)
        self.assertNotIn('atom', detail.lower())
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)
        unquantified.refresh_from_db()
        self.assertIsNone(unquantified.est_qty)

    def test_line_items_from_atoms_per_unit_missing_overrides_returns_400(self):
        """The modal always sends all four overrides for a per-unit bundle;
        a partial body (qty only) must fail field-shaped, not silently mint
        a line with derived defaults."""
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {
            'atoms': [{'type': 'task', 'id': self.pt.pk}],
            'overrides': {'qty': '10'},
            'per_unit': True,
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertIn('description', data)
        self.assertIn('units', data)
        self.assertIn('price', data)
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)

    def test_line_items_from_atoms_per_unit_non_numeric_qty_returns_400(self):
        """A garbage qty must produce a clean 400 (view-boundary coercion),
        not a TypeError from the service's `qty_override <= 0` compare."""
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {
            'atoms': [{'type': 'task', 'id': self.pt.pk}],
            'overrides': {
                'description': 'Bad qty', 'qty': 'not-a-number',
                'units': 'each', 'price': '10.00',
            },
            'per_unit': True,
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('qty', resp.json())
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)

    def test_line_items_from_atoms_non_numeric_qty_whole_line_returns_400(self):
        """Same coercion guard applies to the (default) whole-line path."""
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {
            'atoms': [{'type': 'task', 'id': self.pt.pk}],
            'overrides': {'qty': 'garbage'},
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('qty', resp.json())
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)

    def test_remove_atoms_endpoint(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [
                {'type': 'task', 'id': self.pt.pk},
                {'type': 'material', 'id': self.pm.pk},
            ],
        )
        src_id = li.sources.first().source_id
        url = f'/api/estimates/{self.estimate.pk}/line-items/{li.pk}/remove-atoms/'
        resp = self.client.post(url, {'source_ids': [src_id]}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['line_item_deleted'])

    def test_remove_all_atoms_deletes_line_item(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': self.pt.pk}],
        )
        all_ids = list(li.sources.values_list('source_id', flat=True))
        url = f'/api/estimates/{self.estimate.pk}/line-items/{li.pk}/remove-atoms/'
        resp = self.client.post(url, {'source_ids': all_ids}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['line_item_deleted'])

    def test_line_items_list_includes_sources(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': self.pt.pk}],
        )
        url = f'/api/estimates/{self.estimate.pk}/line-items/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        items = data.get('results', data) if isinstance(data, dict) else data  # handle pagination
        match = next(i for i in items if i['line_item_id'] == li.pk)
        self.assertEqual(len(match['sources']), 1)
        self.assertEqual(match['sources'][0]['source_type'], 'task')


