"""create_on_job accepts source_plan_material so the worksheet→job copy core can
record provenance through the convention-correct service."""

from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.estimates.models import EstWorksheet
from apps.inventory.models import PlanMaterial
from apps.inventory.services import MaterialService


class CreateOnJobProvenanceTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(code='COJ', name='coj')
        self.contact = Contact.objects.create(
            first_name='T', last_name='C', email='coj@test.com')
        self.job = Job.objects.create(job_number='JOB-COJ', contact=self.contact)
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='Bar', quantity=Decimal('2'),
            units='ea', accounting_category=self.ac,
        )

    def test_create_on_job_records_source_plan_material(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='Bar',
            quantity=Decimal('2'), units='ea', accounting_category=self.ac,
            source_plan_material=self.pm,
        )
        self.assertEqual(m.source_plan_material, self.pm)

    def test_create_on_job_defaults_source_plan_material_to_none(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='Loose',
            quantity=Decimal('1'), units='ea', accounting_category=self.ac,
        )
        self.assertIsNone(m.source_plan_material)
