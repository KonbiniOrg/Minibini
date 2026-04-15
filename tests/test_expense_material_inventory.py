"""
Tests for receive_ad_hoc_purchase / reverse_ad_hoc_purchase (QOH only, no earmark).

Note: MaterialService.create_on_job already creates the earmark.
receive_ad_hoc_purchase is QOH-only — it does not touch earmarks.
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.inventory.models import PriceListItem
from apps.inventory.services import InventoryService, MaterialService
from apps.jobs.models import Job


class AdHocPurchaseTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='JOB-AH-1',
            contact=self.contact,
        )

        cat = AccountingCategory.objects.create(code='CAT1', name='c')
        self.pli = PriceListItem.objects.create(
            code='I',
            accounting_category=cat,
            is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_receive_ad_hoc_purchase_bumps_qoh_only(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('12'))

    def test_reverse_ad_hoc_purchase_drops_qoh(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        InventoryService.reverse_ad_hoc_purchase(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))

    def test_receive_ad_hoc_purchase_non_inventoried_is_noop(self):
        """receive_ad_hoc_purchase on a non-inventoried PLI does nothing."""
        cat = AccountingCategory.objects.create(code='CAT2', name='d')
        pli_noninv = PriceListItem.objects.create(
            code='NI', accounting_category=cat, is_inventoried=False,
            qty_on_hand=Decimal('5'),
        )
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='y',
            quantity=Decimal('3'), price_list_item=pli_noninv,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        pli_noninv.refresh_from_db()
        self.assertEqual(pli_noninv.qty_on_hand, Decimal('5'))

    def test_receive_ad_hoc_purchase_no_pli_is_noop(self):
        """receive_ad_hoc_purchase on a material with no PLI does nothing."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='z',
            quantity=Decimal('1'), price_list_item=None,
        )
        # Should not raise
        InventoryService.receive_ad_hoc_purchase(m)
