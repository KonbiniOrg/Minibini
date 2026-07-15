from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, InventoryItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration, AppState


class MaterialResolveOrCreateTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5', email='v@example.com')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = InventoryItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
            inventory_item=self.pli,
        )

    def _args(self, **over):
        defaults = dict(
            job=self.job, inventory_item=self.pli, qty=Decimal('5.00'),
            unit_cost=Decimal('1.00'), description='x', accounting_category=self.cat,
        )
        defaults.update(over)
        return defaults

    def test_explicit_link_via_material_id(self):
        existing = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
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
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        existing.po_line_item = other_line
        existing.save(update_fields=['po_line_item'])
        with self.assertRaises(ValidationError):
            MaterialService.resolve_or_create_for_line(
                self.line, material_id=existing.pk, **self._args(),
            )

    def test_claim_exactly_one_unlinked_pending_material(self):
        existing = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertEqual(result.pk, existing.pk)
        result.refresh_from_db()
        self.assertEqual(result.po_line_item_id, self.line.pk)
        self.assertEqual(result.quantity, Decimal('3.00'))  # plan unchanged

    def test_no_claim_when_multiple_matches_creates_new(self):
        m1 = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        m2 = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('7.00'),
        )
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertNotIn(result.pk, (m1.pk, m2.pk))
        self.assertEqual(result.po_line_item_id, self.line.pk)
        self.assertEqual(result.quantity, Decimal('5.00'))

    def test_no_claim_when_match_is_consumed_creates_new(self):
        consumed = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
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
        self.assertEqual(result.inventory_item_id, self.pli.pk)
        self.assertEqual(result.unit_cost, Decimal('1.00'))

    def test_create_new_pli_less_establishes_and_repoints_line(self):
        """A freeform (pli-less) PO line creates a material and ESTABLISHES it:
        mint a lot at the line price, stamp cost_source='po', and repoint the
        PO line at the minted lot so receiving can bump QOH."""
        freeform_line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='freeform', qty=Decimal('5.00'),
            price=Decimal('7.50'), accounting_category=self.cat,
        )
        result = MaterialService.resolve_or_create_for_line(
            freeform_line, **self._args(inventory_item=None, unit_cost=Decimal('7.50')),
        )
        self.assertEqual(result.quantity, Decimal('5.00'))
        self.assertIsNotNone(result.inventory_item_id)          # minted lot
        self.assertTrue(result.inventory_item.code.startswith('LOT-'))
        self.assertEqual(result.unit_cost, Decimal('7.50'))
        self.assertEqual(result.cost_source, Material.COST_SOURCE_PO)
        self.assertEqual(result.inventory_item.qty_on_hand, Decimal('0.00'))
        # PO line was repointed at the minted lot.
        freeform_line.refresh_from_db()
        self.assertEqual(freeform_line.inventory_item_id, result.inventory_item_id)

    def test_po_link_overrides_estimated_cost(self):
        """Spec: the PO write overrides the placeholder; sell stays locked."""
        material = self._estimated_material(sell=Decimal('400.00'))  # cost_source='estimated'
        li = self._add_po_line(price=Decimal('345.00'))
        result = MaterialService.resolve_or_create_for_line(
            li, material_id=material.pk, job=self.job, inventory_item=None,
            qty=li.qty, unit_cost=li.price, description=li.description,
            accounting_category=self.cat,
        )
        self.assertEqual(result.pk, material.pk)
        material.refresh_from_db()
        self.assertEqual(material.unit_cost, Decimal('345.00'))
        self.assertEqual(material.cost_source, Material.COST_SOURCE_PO)
        self.assertEqual(material.sell_price, Decimal('400.00'))

    def test_explicit_link_to_provisional_establishes_and_repoints(self):
        """Explicit link to a lot-less provisional material establishes it at the
        PO line price (cost_source='po') and repoints a pli-less line."""
        provisional = Material.objects.create(
            job=self.job, inventory_item=None, quantity=Decimal('3.00'),
            sell_price=Decimal('0.00'), accounting_category=self.cat,
            units='ea',
        )
        self.assertIsNone(provisional.cost_source)
        li = self._add_po_line(price=Decimal('12.00'))
        result = MaterialService.resolve_or_create_for_line(
            li, material_id=provisional.pk, job=self.job, inventory_item=None,
            qty=li.qty, unit_cost=li.price, description=li.description,
            accounting_category=self.cat,
        )
        result.refresh_from_db()
        self.assertIsNotNone(result.inventory_item_id)
        self.assertEqual(result.unit_cost, Decimal('12.00'))
        self.assertEqual(result.cost_source, Material.COST_SOURCE_PO)
        li.refresh_from_db()
        self.assertEqual(li.inventory_item_id, result.inventory_item_id)

    def _estimated_material(self, *, sell):
        """A provisional material established with a reverse-markup estimated
        cost — mirrors the acceptance crystallization output (has a lot)."""
        Configuration.objects.get_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})
        m = Material.objects.create(
            job=self.job, inventory_item=None, quantity=Decimal('1.00'),
            sell_price=sell, accounting_category=self.cat, units='ea',
        )
        return MaterialService.establish(
            m, unit_cost=(sell / Decimal('1.25')).quantize(Decimal('0.01')),
            cost_source=Material.COST_SOURCE_ESTIMATED,
        )

    def _add_po_line(self, *, price):
        return PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='ovr', qty=Decimal('1.00'),
            price=price, accounting_category=self.cat,
        )

    def test_explicit_link_with_job_instance_works(self):
        """Defensive: confirm passing a Job instance (not just pk) works."""
        existing = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        result = MaterialService.resolve_or_create_for_line(
            self.line, material_id=existing.pk, **self._args(),
        )
        self.assertEqual(result.pk, existing.pk)

    def test_explicit_link_with_no_job_uses_materials_job(self):
        """When only material_id is given, the Material's job is used."""
        existing = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        args = self._args()
        args.pop('job')  # don't pass job
        result = MaterialService.resolve_or_create_for_line(
            self.line, material_id=existing.pk, **args,
        )
        self.assertEqual(result.pk, existing.pk)
        result.refresh_from_db()
        self.assertEqual(result.po_line_item_id, self.line.pk)

    def test_resolver_raises_when_no_job_and_no_material_id(self):
        args = self._args()
        args.pop('job')
        with self.assertRaises(ValidationError) as ctx:
            MaterialService.resolve_or_create_for_line(self.line, **args)
        self.assertIn('job is required', str(ctx.exception))

    def test_explicit_link_with_mismatched_job_raises(self):
        """If job is given AND material_id is given, they must match."""
        other_contact = Contact.objects.create(first_name='X', last_name='Y', work_number='9', email='xy@example.com')
        other_job = Job.objects.create(job_number='J-2', contact=other_contact, description='other')
        existing = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        args = self._args(job=other_job)  # mismatching job
        with self.assertRaises(ValidationError) as ctx:
            MaterialService.resolve_or_create_for_line(
                self.line, material_id=existing.pk, **args,
            )
        self.assertIn('not on the requested job', str(ctx.exception))
