from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstWorksheet
from apps.estimates.services import EstimateWizardService, EstimateClaimConflict
from apps.jobs.models import Job


class OpenForWorksheetTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_creates_draft_estimate_when_none_exists(self):
        est = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(est.job, self.job)
        self.ws.refresh_from_db()
        self.assertEqual(self.ws.estimate, est)

    def test_returns_existing_draft(self):
        first = EstimateWizardService.open_for_worksheet(self.ws)
        second = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(first.pk, second.pk)

    def test_refuses_finalized_worksheet(self):
        self.ws.status = EstWorksheet.STATUS_FINAL
        self.ws.save()
        with self.assertRaises(ValidationError):
            EstimateWizardService.open_for_worksheet(self.ws)


class ClaimConflictExceptionTest(TestCase):
    def test_exception_carries_atom_ids(self):
        exc = EstimateClaimConflict(atom_ids=[{'type': 'plan_charge', 'id': 1}])
        self.assertEqual(exc.atom_ids, [{'type': 'plan_charge', 'id': 1}])


from apps.estimates.models import EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import PlanMaterial
from apps.jobs.models import PlanCharge, PlanTask, RateScheme


class GetSourcePoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )

        # PlanCharge atom
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup', units='hours',
            est_qty=Decimal('2'), accounting_category=self.cat,
        )
        self.pc = PlanCharge.objects.create(
            plan_task=self.pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('2'),
        )

        # PlanMaterial atom (task-less)
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_pool_has_charge_and_material_atoms(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        atom_ids = [(a['type'], a['id']) for a in pool['atoms']]
        self.assertIn(('plan_charge', self.pc.pk), atom_ids)
        self.assertIn(('plan_material', self.pm.pk), atom_ids)

    def test_atom_amount_uses_compute_amount(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        amounts = {(a['type'], a['id']): a['amount'] for a in pool['atoms']}
        self.assertEqual(amounts[('plan_charge', self.pc.pk)], Decimal('200.00'))
        self.assertEqual(amounts[('plan_material', self.pm.pk)], Decimal('15.00'))

    def test_unclaimed_atom_state(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        for a in pool['atoms']:
            self.assertEqual(a['state'], 'available')

    def test_claimed_atom_state(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('200'), description='', accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_PLAN_CHARGE,
            source_pk=self.pc.pk,
        )
        pool = EstimateWizardService.get_source_pool(self.ws)
        states = {(a['type'], a['id']): a['state'] for a in pool['atoms']}
        self.assertEqual(states[('plan_charge', self.pc.pk)], 'claimed_by_current')
        self.assertEqual(states[('plan_material', self.pm.pk)], 'available')
