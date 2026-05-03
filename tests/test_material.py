from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, PlanTask, RateScheme
from apps.estimates.models import EstWorksheet
from apps.inventory.models import PlanMaterial
from apps.inventory.models import PriceListItem
from apps.core.models import AccountingCategory


class MaterialTestBase(TestCase):
    """Shared setup for material tests."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            job_number='J-MAT-001',
            contact=self.contact,
            description='Test Job',
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
        )
        self.scheme_ac = AccountingCategory.objects.create(
            name='Material-scheme', code='MAT-SCHEME',
        )
        self.scheme = RateScheme.objects.create(
            name='S-mat', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea',
            accounting_category=self.scheme_ac,
        )
        self.task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Install shelving',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
        )
        self.category = AccountingCategory.objects.create(
            name='Material', code='MAT',
        )
        self.inventoried_item = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )
        self.price_list_item = PriceListItem.objects.create(
            code='EDGE.OAK',
            description='Oak edge banding',
            purchase_price=Decimal('12.00'),
            selling_price=Decimal('24.00'),
            accounting_category=self.category,
        )


class MaterialModelTest(MaterialTestBase):
    """Tests for the Material model."""

    def test_create_material_freeform(self):
        """Material with no price list link — a one-off."""
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            description='Custom bracket',
            quantity=Decimal('4.00'),
            unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )
        self.assertEqual(material.description, 'Custom bracket')
        self.assertEqual(material.quantity, Decimal('4.00'))
        self.assertEqual(material.unit_cost, Decimal('5.00'))
        self.assertEqual(material.sell_price, Decimal('10.00'))
        self.assertIsNone(material.price_list_item)

    def test_create_material_with_inventoried_item(self):
        """Material linked to an inventoried item auto-fills fields."""
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            price_list_item=self.inventoried_item,
            quantity=Decimal('3.00'),
        )
        self.assertEqual(material.description, '3/4" Baltic Birch Plywood')
        self.assertEqual(material.unit_cost, Decimal('45.00'))
        self.assertEqual(material.sell_price, Decimal('90.00'))

    def test_create_material_with_price_list_item(self):
        """Material linked to a price list item auto-fills fields."""
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            price_list_item=self.price_list_item,
            quantity=Decimal('10.00'),
        )
        self.assertEqual(material.description, 'Oak edge banding')
        self.assertEqual(material.unit_cost, Decimal('12.00'))
        self.assertEqual(material.sell_price, Decimal('24.00'))

    def test_auto_fill_does_not_overwrite_explicit_values(self):
        """If description/cost/price are provided, auto-fill doesn't overwrite."""
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            price_list_item=self.inventoried_item,
            description='Custom description',
            quantity=Decimal('2.00'),
            unit_cost=Decimal('55.00'),
            sell_price=Decimal('110.00'),
        )
        self.assertEqual(material.description, 'Custom description')
        self.assertEqual(material.unit_cost, Decimal('55.00'))
        self.assertEqual(material.sell_price, Decimal('110.00'))

    def test_total_cost_property(self):
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            description='Screws',
            quantity=Decimal('100.00'),
            unit_cost=Decimal('0.10'),
            sell_price=Decimal('0.20'),
        )
        self.assertEqual(material.total_cost, Decimal('10.00'))

    def test_total_sell_property(self):
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            description='Screws',
            quantity=Decimal('100.00'),
            unit_cost=Decimal('0.10'),
            sell_price=Decimal('0.20'),
        )
        self.assertEqual(material.total_sell, Decimal('20.00'))

    def test_material_requires_task(self):
        """Material must be attached to a task."""
        material = PlanMaterial(
            description='Orphan material',
            quantity=Decimal('1.00'),
            unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )
        with self.assertRaises(ValidationError):
            material.full_clean()

    def test_cascade_on_task_delete(self):
        """Materials are deleted when their task is deleted."""
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            description='Will be deleted',
            quantity=Decimal('1.00'),
        )
        plan_material_id = material.plan_material_id
        self.task.delete()
        self.assertFalse(PlanMaterial.objects.filter(plan_material_id=plan_material_id).exists())

    def test_set_null_on_price_list_item_delete(self):
        """Price list item FK set to null when price list item is deleted."""
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            price_list_item=self.price_list_item,
            quantity=Decimal('1.00'),
        )
        self.price_list_item.delete()
        material.refresh_from_db()
        self.assertIsNone(material.price_list_item)

    def test_task_can_have_multiple_materials(self):
        """A task can have several materials attached."""
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task, description='Plywood',
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task, description='Screws',
            quantity=Decimal('50.00'), unit_cost=Decimal('0.05'), sell_price=Decimal('0.10'),
        )
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task, description='Glue',
            quantity=Decimal('1.00'), unit_cost=Decimal('8.00'), sell_price=Decimal('12.00'),
        )
        self.assertEqual(self.task.plan_materials.count(), 3)

    def test_pli_auto_fills_accounting_category(self):
        """Material linked to a PLI auto-fills accounting_category from PLI."""
        lit, _ = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})
        self.inventoried_item.accounting_category = lit
        self.inventoried_item.save()

        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            price_list_item=self.inventoried_item,
            quantity=Decimal('2.00'),
        )
        self.assertEqual(material.accounting_category, lit)

    def test_explicit_accounting_category_not_overwritten_by_pli(self):
        """Explicit accounting_category on material is not overwritten by PLI."""
        lit_mat, _ = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})
        lit_labor, _ = AccountingCategory.objects.get_or_create(code='LBR', defaults={'name': 'Labor'})
        self.inventoried_item.accounting_category = lit_mat
        self.inventoried_item.save()

        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            price_list_item=self.inventoried_item,
            quantity=Decimal('2.00'),
            accounting_category=lit_labor,
        )
        self.assertEqual(material.accounting_category, lit_labor)

    def test_str_representation(self):
        material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            description='Edge banding',
            quantity=Decimal('20.00'),
        )
        self.assertEqual(str(material), 'Edge banding (qty: 20.00)')


class MaterialWorksheetVersioningTest(MaterialTestBase):
    """Tests that worksheet versioning copies materials."""

    def test_version_copies_materials(self):
        """Creating a new worksheet version copies materials on tasks."""
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            price_list_item=self.inventoried_item,
            description='Plywood',
            quantity=Decimal('3.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            description='Custom bracket',
            quantity=Decimal('4.00'),
            unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )

        new_worksheet = self.worksheet.create_new_version()

        # New worksheet should have a task with 2 materials
        new_tasks = new_worksheet.plan_tasks.all()
        self.assertEqual(new_tasks.count(), 1)
        new_task = new_tasks.first()
        new_materials = new_task.plan_materials.all()
        self.assertEqual(new_materials.count(), 2)

        # Verify material data was copied
        plywood = new_materials.get(description='Plywood')
        self.assertEqual(plywood.price_list_item, self.inventoried_item)
        self.assertEqual(plywood.quantity, Decimal('3.00'))
        self.assertEqual(plywood.unit_cost, Decimal('45.00'))
        self.assertEqual(plywood.sell_price, Decimal('90.00'))

        bracket = new_materials.get(description='Custom bracket')
        self.assertIsNone(bracket.price_list_item)
        self.assertEqual(bracket.quantity, Decimal('4.00'))

    def test_version_materials_are_independent(self):
        """Modifying materials on new version doesn't affect original."""
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.task,
            description='Original material',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
        )

        new_worksheet = self.worksheet.create_new_version()

        new_task = new_worksheet.plan_tasks.first()
        new_material = new_task.plan_materials.first()
        new_material.quantity = Decimal('99.00')
        new_material.save()

        # Original should be unchanged
        original_material = self.task.plan_materials.first()
        self.assertEqual(original_material.quantity, Decimal('5.00'))
