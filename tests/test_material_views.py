from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, EstWorksheet, Task, Material
from apps.invoicing.models import PriceListItem


class MaterialViewTestBase(TestCase):
    """Shared setup for material view tests."""

    def setUp(self):
        self.client = Client()
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
            job_number='J-MV-001',
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
        self.inventoried_item = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
        )
        self.price_list_item = PriceListItem.objects.create(
            code='EDGE.OAK',
            description='Oak edge banding',
            purchase_price=Decimal('12.00'),
            selling_price=Decimal('24.00'),
        )


class MaterialAddViewTest(MaterialViewTestBase):
    """Tests for the material_add view."""

    def test_add_material_get(self):
        """GET renders the add material form."""
        url = reverse('jobs:material_add', args=[self.task.task_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Material')

    def test_add_material_post_freeform(self):
        """POST creates a freeform material and redirects."""
        url = reverse('jobs:material_add', args=[self.task.task_id])
        response = self.client.post(url, {
            'description': 'Custom bracket',
            'quantity': '4.00',
            'unit_cost': '5.00',
            'sell_price': '10.00',
        })
        self.assertEqual(response.status_code, 302)
        material = Material.objects.get(description='Custom bracket')
        self.assertEqual(material.task, self.task)
        self.assertEqual(material.quantity, Decimal('4.00'))

    def test_add_material_post_with_price_list_item(self):
        """POST with price_list_item auto-fills fields."""
        url = reverse('jobs:material_add', args=[self.task.task_id])
        response = self.client.post(url, {
            'price_list_item': self.inventoried_item.pk,
            'quantity': '3.00',
            'description': '',
            'unit_cost': '0.00',
            'sell_price': '0.00',
        })
        self.assertEqual(response.status_code, 302)
        material = Material.objects.get(task=self.task)
        self.assertEqual(material.description, '3/4" Baltic Birch Plywood')
        self.assertEqual(material.unit_cost, Decimal('45.00'))

    def test_add_material_blocked_on_non_draft_worksheet(self):
        """Cannot add materials to tasks on non-draft worksheets."""
        self.worksheet.status = 'submitted'
        self.worksheet.save()
        url = reverse('jobs:material_add', args=[self.task.task_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)


class MaterialEditViewTest(MaterialViewTestBase):
    """Tests for the material_edit view."""

    def setUp(self):
        super().setUp()
        self.material = Material.objects.create(
            task=self.task,
            description='Original material',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
        )

    def test_edit_material_get(self):
        """GET renders the edit material form with existing data."""
        url = reverse('jobs:material_edit', args=[self.material.material_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Original material')

    def test_edit_material_post(self):
        """POST updates the material and redirects."""
        url = reverse('jobs:material_edit', args=[self.material.material_id])
        response = self.client.post(url, {
            'description': 'Updated material',
            'quantity': '10.00',
            'unit_cost': '15.00',
            'sell_price': '30.00',
        })
        self.assertEqual(response.status_code, 302)
        self.material.refresh_from_db()
        self.assertEqual(self.material.description, 'Updated material')
        self.assertEqual(self.material.quantity, Decimal('10.00'))

    def test_edit_material_blocked_on_non_draft_worksheet(self):
        """Cannot edit materials on tasks on non-draft worksheets."""
        self.worksheet.status = 'submitted'
        self.worksheet.save()
        url = reverse('jobs:material_edit', args=[self.material.material_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)


class MaterialDeleteViewTest(MaterialViewTestBase):
    """Tests for the material_delete view."""

    def setUp(self):
        super().setUp()
        self.material = Material.objects.create(
            task=self.task,
            description='To be deleted',
            quantity=Decimal('1.00'),
            unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )

    def test_delete_material(self):
        """POST deletes the material and redirects to task detail."""
        url = reverse('jobs:material_delete', args=[self.material.material_id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Material.objects.filter(material_id=self.material.material_id).exists())

    def test_delete_material_blocked_on_non_draft_worksheet(self):
        """Cannot delete materials on tasks on non-draft worksheets."""
        self.worksheet.status = 'submitted'
        self.worksheet.save()
        url = reverse('jobs:material_delete', args=[self.material.material_id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        # Material should still exist
        self.assertTrue(Material.objects.filter(material_id=self.material.material_id).exists())
