from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration


class MaterialLinkToPOLineTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat,
        )
        po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )

    def _make_material(self, **kwargs):
        defaults = dict(job=self.job, quantity=Decimal('5.00'), accounting_category=self.cat)
        defaults.update(kwargs)
        return Material.objects.create(**defaults)

    def test_link_to_po_line_sets_fk(self):
        m = self._make_material()
        MaterialService.link_to_po_line(m, self.line)
        m.refresh_from_db()
        self.assertEqual(m.po_line_item_id, self.line.pk)

    def test_link_to_same_line_is_idempotent(self):
        m = self._make_material(po_line_item=self.line)
        MaterialService.link_to_po_line(m, self.line)  # must not raise
        m.refresh_from_db()
        self.assertEqual(m.po_line_item_id, self.line.pk)

    def test_link_refuses_consumed_material(self):
        m = self._make_material(consumption_state=Material.CONSUMPTION_STATE_CONSUMED)
        with self.assertRaises(ValidationError):
            MaterialService.link_to_po_line(m, self.line)

    def test_link_refuses_already_linked_material(self):
        other_line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.line.purchase_order,
            description='y', qty=Decimal('1.00'), price=Decimal('1.00'),
        )
        m = self._make_material(po_line_item=other_line)
        with self.assertRaises(ValidationError):
            MaterialService.link_to_po_line(m, self.line)

    def test_unlink_clears_fk(self):
        m = self._make_material(po_line_item=self.line)
        MaterialService.unlink_from_po_line(m)
        m.refresh_from_db()
        self.assertIsNone(m.po_line_item_id)

    def test_unlink_when_already_unlinked_is_no_op(self):
        m = self._make_material()  # po_line_item is None by default
        MaterialService.unlink_from_po_line(m)  # must not raise
        m.refresh_from_db()
        self.assertIsNone(m.po_line_item_id)

    def test_unlink_refuses_consumed_material(self):
        m = self._make_material(po_line_item=self.line, consumption_state=Material.CONSUMPTION_STATE_CONSUMED)
        with self.assertRaises(ValidationError):
            MaterialService.unlink_from_po_line(m)
