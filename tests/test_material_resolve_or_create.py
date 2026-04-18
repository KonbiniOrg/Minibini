from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration


class MaterialResolveOrCreateTest(TestCase):
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
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_inventoried=True,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
            price_list_item=self.pli,
        )

    def _args(self, **over):
        defaults = dict(
            job=self.job, price_list_item=self.pli, qty=Decimal('5.00'),
            unit_cost=Decimal('1.00'), description='x', accounting_category=self.cat,
        )
        defaults.update(over)
        return defaults

    def test_explicit_link_via_material_id(self):
        existing = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        result = MaterialService.resolve_or_create_for_line(
            self.line, material_id=existing.pk, **self._args(qty=Decimal('10.00')),
        )
        self.assertEqual(result.pk, existing.pk)
        result.refresh_from_db()
        self.assertEqual(result.po_line_item_id, self.line.pk)
        # Plan unchanged by resolver
        self.assertEqual(result.quantity, Decimal('3.00'))

    def test_explicit_link_raises_if_material_already_linked(self):
        other_line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='y', qty=Decimal('1.00'), price=Decimal('1.00'),
        )
        existing = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        existing.po_line_item = other_line
        existing.save(update_fields=['po_line_item'])
        with self.assertRaises(ValidationError):
            MaterialService.resolve_or_create_for_line(
                self.line, material_id=existing.pk, **self._args(),
            )

    def test_claim_exactly_one_unlinked_pending_material(self):
        existing = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertEqual(result.pk, existing.pk)
        result.refresh_from_db()
        self.assertEqual(result.po_line_item_id, self.line.pk)
        self.assertEqual(result.quantity, Decimal('3.00'))  # plan unchanged

    def test_no_claim_when_multiple_matches_creates_new(self):
        m1 = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        m2 = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('7.00'),
        )
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertNotIn(result.pk, (m1.pk, m2.pk))
        self.assertEqual(result.po_line_item_id, self.line.pk)
        self.assertEqual(result.quantity, Decimal('5.00'))

    def test_no_claim_when_match_is_consumed_creates_new(self):
        consumed = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        consumed.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        consumed.save(update_fields=['consumption_state'])
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertNotEqual(result.pk, consumed.pk)
        self.assertEqual(result.po_line_item_id, self.line.pk)

    def test_create_new_when_no_match(self):
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertEqual(result.quantity, Decimal('5.00'))
        self.assertEqual(result.po_line_item_id, self.line.pk)
        self.assertEqual(result.job_id, self.job.pk)
        self.assertEqual(result.price_list_item_id, self.pli.pk)
        self.assertEqual(result.unit_cost, Decimal('1.00'))

    def test_create_new_pli_less(self):
        result = MaterialService.resolve_or_create_for_line(
            self.line, **self._args(price_list_item=None),
        )
        self.assertIsNone(result.price_list_item_id)
        self.assertEqual(result.quantity, Decimal('5.00'))
