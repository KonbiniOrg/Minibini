"""freeform_kind replaced the retired is_material boolean field (task-owned-
money Phase 2 Task 2). These tests originally exercised the is_material
model field directly — inherited red once that field was removed (no
model-level alias exists; only the service-layer `is_material` kwarg does).
Rewritten to exercise freeform_kind itself."""
from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import Estimate, EstimateLineItem
from apps.jobs.models import Job


class EstimateLineItemFreeformKindFieldTest(TestCase):
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

    def test_defaults_null(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='x',
            qty=Decimal('1'), price=Decimal('1'), accounting_category=self.cat,
        )
        li.refresh_from_db()
        self.assertIsNone(li.freeform_kind)

    def test_persists_material(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='ply',
            qty=Decimal('1'), price=Decimal('1'), accounting_category=self.cat,
            freeform_kind=EstimateLineItem.KIND_MATERIAL,
        )
        li.refresh_from_db()
        self.assertEqual(li.freeform_kind, EstimateLineItem.KIND_MATERIAL)
