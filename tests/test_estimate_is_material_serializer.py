"""freeform_kind replaced the retired is_material boolean (task-owned-money
Phase 2 Task 2). This test originally checked that the serializer exposed
'is_material' — inherited red once the serializer switched to exposing the
real field. Rewritten to confirm freeform_kind is what's serialized
(Task 4: readable everywhere the line is serialized)."""
from decimal import Decimal
from django.test import TestCase

from apps.api.estimates.serializers import EstimateLineItemSerializer
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import Estimate, EstimateLineItem
from apps.jobs.models import Job


class EstimateLineItemSerializerFreeformKindTest(TestCase):
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

    def test_freeform_kind_serialized(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='ply',
            qty=Decimal('1'), price=Decimal('1'), accounting_category=self.cat,
            freeform_kind=EstimateLineItem.KIND_MATERIAL,
        )
        data = EstimateLineItemSerializer(li).data
        self.assertIn('freeform_kind', data)
        self.assertEqual(data['freeform_kind'], EstimateLineItem.KIND_MATERIAL)
