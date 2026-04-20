from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, User
from apps.estimates.models import Estimate, EstWorksheet, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import PlanMaterial
from apps.jobs.models import Job, PlanCharge, PlanTask, RateScheme


class EstimateWizardAPITest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
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
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup', units='hours',
            est_qty=Decimal('2'), accounting_category=self.cat,
        )
        self.pc = PlanCharge.objects.create(
            plan_task=self.pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('2'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_source_pool_endpoint(self):
        url = f'/api/estimates/{self.estimate.pk}/source-pool/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('atoms', data)
        types = [a['type'] for a in data['atoms']]
        self.assertIn('plan_charge', types)
        self.assertIn('plan_material', types)

    def test_line_items_from_atoms_endpoint(self):
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {'atoms': [{'type': 'plan_charge', 'id': self.pc.pk}]}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 1)

    def test_line_items_from_atoms_conflict_returns_409(self):
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {'atoms': [{'type': 'plan_charge', 'id': self.pc.pk}]}
        self.client.post(url, payload, format='json')
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], 'atoms_already_claimed')

    def test_add_atoms_to_existing_line_item(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_charge', 'id': self.pc.pk}],
        )
        url = f'/api/estimates/{self.estimate.pk}/line-items/{li.pk}/add-atoms/'
        payload = {'atoms': [{'type': 'plan_material', 'id': self.pm.pk}]}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.sources.count(), 2)

    def test_remove_atoms_endpoint(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [
                {'type': 'plan_charge', 'id': self.pc.pk},
                {'type': 'plan_material', 'id': self.pm.pk},
            ],
        )
        src_id = li.sources.first().source_id
        url = f'/api/estimates/{self.estimate.pk}/line-items/{li.pk}/remove-atoms/'
        resp = self.client.post(url, {'source_ids': [src_id]}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['line_item_deleted'])

    def test_remove_all_atoms_deletes_line_item(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_charge', 'id': self.pc.pk}],
        )
        all_ids = list(li.sources.values_list('source_id', flat=True))
        url = f'/api/estimates/{self.estimate.pk}/line-items/{li.pk}/remove-atoms/'
        resp = self.client.post(url, {'source_ids': all_ids}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['line_item_deleted'])
