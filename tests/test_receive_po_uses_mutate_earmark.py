from unittest.mock import patch
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem, Earmark
from apps.inventory.services import InventoryService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class ReceivePoLineItemUsesMutateEarmarkTest(TestCase):
    def test_receive_po_line_item_routes_through_mutate_earmark(self):
        cat = AccountingCategory.objects.create(name='c')
        pli = PriceListItem.objects.create(
            code='P', accounting_category=cat, is_inventoried=True,
        )
        contact = Contact.objects.create(first_name='V', last_name='Ndr')
        biz = Business.objects.create(business_name='Acme', default_contact=contact)
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='JOB-RP-1', contact=contact)
        po = PurchaseOrder.objects.create(business=biz, po_number='PO-TEST-1')
        pli_line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, price_list_item=pli, qty=Decimal('5'),
            job=job, description='x',
        )
        with patch.object(InventoryService, '_mutate_earmark') as m:
            InventoryService.receive_po_line_item(pli_line)
            m.assert_called_once_with(pli, job, Decimal('5'))
