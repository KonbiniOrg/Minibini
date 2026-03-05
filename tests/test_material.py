from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, EstWorksheet, Task, Material
from apps.inventory.models import InventoryItem
from apps.invoicing.models import PriceListItem


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
        self.task = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Install shelving',
            rate=Decimal('50.00'),
            est_qty=Decimal('4.00'),
        )
        self.inventory_item = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
        )
        self.price_list_item = PriceListItem.objects.create(
            code='EDGE.OAK',
            description='Oak edge banding',
            purchase_price=Decimal('12.00'),
            selling_price=Decimal('24.00'),
        )


class MaterialModelTest(MaterialTestBase):
    """Tests for the Material model."""

    def test_create_material_freeform(self):
        """Material with no inventory or price list link — a one-off."""
        material = Material.objects.create(
            task=self.task,
            description='Custom bracket',
            quantity=Decimal('4.00'),
            unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )
        self.assertEqual(material.description, 'Custom bracket')
        self.assertEqual(material.quantity, Decimal('4.00'))
        self.assertEqual(material.unit_cost, Decimal('5.00'))
        self.assertEqual(material.sell_price, Decimal('10.00'))
        self.assertIsNone(material.inventory_item)
        self.assertIsNone(material.price_list_item)

    def test_create_material_with_inventory_item(self):
        """Material linked to an inventory item auto-fills fields."""
        material = Material.objects.create(
            task=self.task,
            inventory_item=self.inventory_item,
            quantity=Decimal('3.00'),
        )
        self.assertEqual(material.description, '3/4" Baltic Birch Plywood')
        self.assertEqual(material.unit_cost, Decimal('45.00'))
        self.assertEqual(material.sell_price, Decimal('90.00'))

    def test_create_material_with_price_list_item(self):
        """Material linked to a price list item auto-fills fields."""
        material = Material.objects.create(
            task=self.task,
            price_list_item=self.price_list_item,
            quantity=Decimal('10.00'),
        )
        self.assertEqual(material.description, 'Oak edge banding')
        self.assertEqual(material.unit_cost, Decimal('12.00'))
        self.assertEqual(material.sell_price, Decimal('24.00'))

    def test_cannot_have_both_inventory_and_price_list(self):
        """Validation error if both inventory_item and price_list_item are set."""
        material = Material(
            task=self.task,
            inventory_item=self.inventory_item,
            price_list_item=self.price_list_item,
            description='Conflict',
            quantity=Decimal('1.00'),
        )
        with self.assertRaises(ValidationError):
            material.full_clean()

    def test_auto_fill_does_not_overwrite_explicit_values(self):
        """If description/cost/price are provided, auto-fill doesn't overwrite."""
        material = Material.objects.create(
            task=self.task,
            inventory_item=self.inventory_item,
            description='Custom description',
            quantity=Decimal('2.00'),
            unit_cost=Decimal('55.00'),
            sell_price=Decimal('110.00'),
        )
        self.assertEqual(material.description, 'Custom description')
        self.assertEqual(material.unit_cost, Decimal('55.00'))
        self.assertEqual(material.sell_price, Decimal('110.00'))

    def test_total_cost_property(self):
        material = Material.objects.create(
            task=self.task,
            description='Screws',
            quantity=Decimal('100.00'),
            unit_cost=Decimal('0.10'),
            sell_price=Decimal('0.20'),
        )
        self.assertEqual(material.total_cost, Decimal('10.00'))

    def test_total_sell_property(self):
        material = Material.objects.create(
            task=self.task,
            description='Screws',
            quantity=Decimal('100.00'),
            unit_cost=Decimal('0.10'),
            sell_price=Decimal('0.20'),
        )
        self.assertEqual(material.total_sell, Decimal('20.00'))

    def test_material_requires_task(self):
        """Material must be attached to a task."""
        material = Material(
            description='Orphan material',
            quantity=Decimal('1.00'),
            unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )
        with self.assertRaises(ValidationError):
            material.full_clean()

    def test_cascade_on_task_delete(self):
        """Materials are deleted when their task is deleted."""
        material = Material.objects.create(
            task=self.task,
            description='Will be deleted',
            quantity=Decimal('1.00'),
        )
        material_id = material.material_id
        self.task.delete()
        self.assertFalse(Material.objects.filter(material_id=material_id).exists())

    def test_set_null_on_inventory_item_delete(self):
        """Inventory item FK set to null when inventory item is deleted."""
        material = Material.objects.create(
            task=self.task,
            inventory_item=self.inventory_item,
            quantity=Decimal('1.00'),
        )
        self.inventory_item.delete()
        material.refresh_from_db()
        self.assertIsNone(material.inventory_item)

    def test_set_null_on_price_list_item_delete(self):
        """Price list item FK set to null when price list item is deleted."""
        material = Material.objects.create(
            task=self.task,
            price_list_item=self.price_list_item,
            quantity=Decimal('1.00'),
        )
        # PriceListItem uses soft delete in practice, but SET_NULL handles hard delete
        self.price_list_item.delete()
        material.refresh_from_db()
        self.assertIsNone(material.price_list_item)

    def test_task_can_have_multiple_materials(self):
        """A task can have several materials attached."""
        m1 = Material.objects.create(
            task=self.task, description='Plywood',
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        m2 = Material.objects.create(
            task=self.task, description='Screws',
            quantity=Decimal('50.00'), unit_cost=Decimal('0.05'), sell_price=Decimal('0.10'),
        )
        m3 = Material.objects.create(
            task=self.task, description='Glue',
            quantity=Decimal('1.00'), unit_cost=Decimal('8.00'), sell_price=Decimal('12.00'),
        )
        self.assertEqual(self.task.materials.count(), 3)

    def test_str_representation(self):
        material = Material.objects.create(
            task=self.task,
            description='Edge banding',
            quantity=Decimal('20.00'),
        )
        self.assertEqual(str(material), 'Edge banding (qty: 20.00)')


class MaterialWorksheetVersioningTest(MaterialTestBase):
    """Tests that worksheet versioning copies materials."""

    def test_version_copies_materials(self):
        """Creating a new worksheet version copies materials on tasks."""
        Material.objects.create(
            task=self.task,
            inventory_item=self.inventory_item,
            description='Plywood',
            quantity=Decimal('3.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=self.task,
            description='Custom bracket',
            quantity=Decimal('4.00'),
            unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )

        new_worksheet = self.worksheet.create_new_version()

        # New worksheet should have a task with 2 materials
        new_tasks = new_worksheet.task_set.all()
        self.assertEqual(new_tasks.count(), 1)
        new_task = new_tasks.first()
        new_materials = new_task.materials.all()
        self.assertEqual(new_materials.count(), 2)

        # Verify material data was copied
        plywood = new_materials.get(description='Plywood')
        self.assertEqual(plywood.inventory_item, self.inventory_item)
        self.assertEqual(plywood.quantity, Decimal('3.00'))
        self.assertEqual(plywood.unit_cost, Decimal('45.00'))
        self.assertEqual(plywood.sell_price, Decimal('90.00'))

        bracket = new_materials.get(description='Custom bracket')
        self.assertIsNone(bracket.inventory_item)
        self.assertEqual(bracket.quantity, Decimal('4.00'))

    def test_version_materials_are_independent(self):
        """Modifying materials on new version doesn't affect original."""
        Material.objects.create(
            task=self.task,
            description='Original material',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
        )

        new_worksheet = self.worksheet.create_new_version()

        new_task = new_worksheet.task_set.first()
        new_material = new_task.materials.first()
        new_material.quantity = Decimal('99.00')
        new_material.save()

        # Original should be unchanged
        original_material = self.task.materials.first()
        self.assertEqual(original_material.quantity, Decimal('5.00'))
