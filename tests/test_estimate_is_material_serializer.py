from decimal import Decimal
from django.test import TestCase

from apps.api.estimates.serializers import EstimateLineItemSerializer
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import Estimate, EstimateLineItem
from apps.jobs.models import Job


class EstimateLineItemSerializerIsMaterialTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='Mat', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )

    def test_is_material_serialized(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='ply',
            qty=Decimal('1'), price=Decimal('1'), accounting_category=self.cat,
            is_material=True,
        )
        data = EstimateLineItemSerializer(li).data
        self.assertIn('is_material', data)
        self.assertIs(data['is_material'], True)
