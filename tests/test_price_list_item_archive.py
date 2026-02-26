"""Tests for PriceListItem archive functionality."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse

from apps.invoicing.models import PriceListItem
from apps.invoicing.forms import PriceListItemForm
from apps.jobs.forms import PriceListLineItemForm
from apps.jobs.models import Job, Estimate, EstimateLineItem
from apps.purchasing.forms import POPriceListLineItemForm, PurchaseOrderLineItemForm, BillLineItemForm
from apps.contacts.models import Contact


class PriceListItemArchiveListViewTest(TestCase):
    """Tests for price list item list view archive filtering."""

    def setUp(self):
        self.client = Client()
        # Create active items
        self.active_item1 = PriceListItem.objects.create(
            code='ACTIVE001',
            description='Active Item 1',
            selling_price=Decimal('10.00'),
            is_active=True
        )
        self.active_item2 = PriceListItem.objects.create(
            code='ACTIVE002',
            description='Active Item 2',
            selling_price=Decimal('20.00'),
            is_active=True
        )
        # Create archived items
        self.archived_item1 = PriceListItem.objects.create(
            code='ARCHIVED001',
            description='Archived Item 1',
            selling_price=Decimal('30.00'),
            is_active=False
        )
        self.archived_item2 = PriceListItem.objects.create(
            code='ARCHIVED002',
            description='Archived Item 2',
            selling_price=Decimal('40.00'),
            is_active=False
        )

    def test_list_view_defaults_to_active_only(self):
        """Test that list view shows only active items by default."""
        response = self.client.get(reverse('invoicing:price_list_item_list'))
        self.assertEqual(response.status_code, 200)

        # Should show active items
        self.assertContains(response, 'ACTIVE001')
        self.assertContains(response, 'ACTIVE002')

        # Should not show archived items
        self.assertNotContains(response, 'ARCHIVED001')
        self.assertNotContains(response, 'ARCHIVED002')

    def test_list_view_show_archived_parameter(self):
        """Test that show_archived=1 shows all items including archived."""
        response = self.client.get(
            reverse('invoicing:price_list_item_list') + '?show_archived=1'
        )
        self.assertEqual(response.status_code, 200)

        # Should show all items
        self.assertContains(response, 'ACTIVE001')
        self.assertContains(response, 'ACTIVE002')
        self.assertContains(response, 'ARCHIVED001')
        self.assertContains(response, 'ARCHIVED002')

    def test_list_view_shows_archived_indicator(self):
        """Test that archived items show 'Archived' status."""
        response = self.client.get(
            reverse('invoicing:price_list_item_list') + '?show_archived=1'
        )
        self.assertEqual(response.status_code, 200)

        # Check for status indicators
        content = response.content.decode()
        self.assertIn('<strong>Archived</strong>', content)
        self.assertIn('Active', content)

    def test_list_view_show_archived_link(self):
        """Test that 'Show Archived' link appears when not showing archived."""
        response = self.client.get(reverse('invoicing:price_list_item_list'))
        self.assertContains(response, 'Show Archived')
        self.assertNotContains(response, 'Hide Archived')

    def test_list_view_hide_archived_link(self):
        """Test that 'Hide Archived' link appears when showing archived."""
        response = self.client.get(
            reverse('invoicing:price_list_item_list') + '?show_archived=1'
        )
        self.assertContains(response, 'Hide Archived')
        self.assertNotContains(response, 'Show Archived')

    def test_show_archived_context_variable(self):
        """Test that show_archived context variable is set correctly."""
        # Without parameter
        response = self.client.get(reverse('invoicing:price_list_item_list'))
        self.assertFalse(response.context['show_archived'])

        # With parameter
        response = self.client.get(
            reverse('invoicing:price_list_item_list') + '?show_archived=1'
        )
        self.assertTrue(response.context['show_archived'])


class PriceListItemFormArchiveTest(TestCase):
    """Tests for PriceListItemForm archive field handling."""

    def test_create_form_does_not_have_is_active_field(self):
        """Test that create form does not include is_active field."""
        form = PriceListItemForm()
        self.assertNotIn('is_active', form.fields)

    def test_edit_form_has_is_active_field(self):
        """Test that edit form includes is_active field."""
        item = PriceListItem.objects.create(
            code='TEST001',
            description='Test Item',
            selling_price=Decimal('10.00')
        )
        form = PriceListItemForm(instance=item)
        self.assertIn('is_active', form.fields)
        self.assertEqual(
            form.fields['is_active'].label,
            "Active (uncheck to archive)"
        )

    def test_new_item_created_as_active(self):
        """Test that new items are created as active by default."""
        form = PriceListItemForm(data={
            'code': 'NEW001',
            'description': 'New Item',
            'selling_price': '10.00',
            'purchase_price': '5.00',
            'qty_on_hand': '0.00',
            'qty_sold': '0.00',
            'qty_wasted': '0.00',
        })
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.assertTrue(item.is_active)

    def test_archive_item_via_edit_form(self):
        """Test archiving an item through the edit form."""
        item = PriceListItem.objects.create(
            code='TEST001',
            description='Test Item',
            selling_price=Decimal('10.00'),
            is_active=True
        )

        form = PriceListItemForm(
            data={
                'code': 'TEST001',
                'description': 'Test Item',
                'selling_price': '10.00',
                'purchase_price': '0.00',
                'qty_on_hand': '0.00',
                'qty_sold': '0.00',
                'qty_wasted': '0.00',
                'is_active': False,  # Unchecking the box
            },
            instance=item
        )
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.assertFalse(item.is_active)

    def test_restore_archived_item_via_edit_form(self):
        """Test restoring an archived item through the edit form."""
        item = PriceListItem.objects.create(
            code='TEST001',
            description='Test Item',
            selling_price=Decimal('10.00'),
            is_active=False
        )

        form = PriceListItemForm(
            data={
                'code': 'TEST001',
                'description': 'Test Item',
                'selling_price': '10.00',
                'purchase_price': '0.00',
                'qty_on_hand': '0.00',
                'qty_sold': '0.00',
                'qty_wasted': '0.00',
                'is_active': True,  # Checking the box
            },
            instance=item
        )
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.assertTrue(item.is_active)


class PriceListItemFormArchiveViewTest(TestCase):
    """Tests for archive functionality through views."""

    def setUp(self):
        self.client = Client()

    def test_edit_view_shows_archived_warning(self):
        """Test that edit view shows warning for archived items."""
        item = PriceListItem.objects.create(
            code='ARCHIVED001',
            description='Archived Item',
            selling_price=Decimal('10.00'),
            is_active=False
        )

        response = self.client.get(
            reverse('invoicing:price_list_item_edit', args=[item.price_list_item_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This item is archived')

    def test_edit_view_no_warning_for_active_items(self):
        """Test that edit view does not show warning for active items."""
        item = PriceListItem.objects.create(
            code='ACTIVE001',
            description='Active Item',
            selling_price=Decimal('10.00'),
            is_active=True
        )

        response = self.client.get(
            reverse('invoicing:price_list_item_edit', args=[item.price_list_item_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'This item is archived')


class PriceListItemSelectionFormFilterTest(TestCase):
    """Tests for filtering archived items from selection forms."""

    def setUp(self):
        self.active_item = PriceListItem.objects.create(
            code='ACTIVE001',
            description='Active Item',
            selling_price=Decimal('10.00'),
            is_active=True
        )
        self.archived_item = PriceListItem.objects.create(
            code='ARCHIVED001',
            description='Archived Item',
            selling_price=Decimal('20.00'),
            is_active=False
        )

    def test_price_list_line_item_form_filters_archived(self):
        """Test PriceListLineItemForm only shows active items."""
        form = PriceListLineItemForm()
        queryset = form.fields['price_list_item'].queryset

        self.assertIn(self.active_item, queryset)
        self.assertNotIn(self.archived_item, queryset)

    def test_po_price_list_line_item_form_filters_archived(self):
        """Test POPriceListLineItemForm only shows active items."""
        form = POPriceListLineItemForm()
        queryset = form.fields['price_list_item'].queryset

        self.assertIn(self.active_item, queryset)
        self.assertNotIn(self.archived_item, queryset)

    def test_purchase_order_line_item_form_filters_archived(self):
        """Test PurchaseOrderLineItemForm only shows active items."""
        form = PurchaseOrderLineItemForm()
        queryset = form.fields['price_list_item'].queryset

        self.assertIn(self.active_item, queryset)
        self.assertNotIn(self.archived_item, queryset)

    def test_bill_line_item_form_filters_archived(self):
        """Test BillLineItemForm only shows active items."""
        form = BillLineItemForm()
        queryset = form.fields['price_list_item'].queryset

        self.assertIn(self.active_item, queryset)
        self.assertNotIn(self.archived_item, queryset)


class ArchivedPriceListItemDisplayTest(TestCase):
    """Tests for displaying archived indicator on line items."""

    def setUp(self):
        self.client = Client()

        # Create contact and job
        self.contact = Contact.objects.create(
            first_name='Test',
            last_name='User',
            email='test@example.com'
        )
        self.job = Job.objects.create(
            job_number='TEST-001',
            contact=self.contact
        )

        # Create active and archived price list items
        self.active_item = PriceListItem.objects.create(
            code='ACTIVE001',
            description='Active Item',
            selling_price=Decimal('10.00'),
            is_active=True
        )
        self.archived_item = PriceListItem.objects.create(
            code='ARCHIVED001',
            description='Archived Item',
            selling_price=Decimal('20.00'),
            is_active=False
        )

        # Create estimate with line items
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-TEST-001',
            status='draft'
        )

    def test_estimate_detail_shows_archived_indicator(self):
        """Test that estimate detail shows (Archived) for archived price list items."""
        # Create line item with archived price list item
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            price_list_item=self.archived_item,
            description='Line with archived item',
            qty=Decimal('1.00'),
            price=Decimal('20.00')
        )

        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '(Archived)')

    def test_estimate_detail_no_indicator_for_active(self):
        """Test that estimate detail does not show (Archived) for active items."""
        # Create line item with active price list item
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            price_list_item=self.active_item,
            description='Line with active item',
            qty=Decimal('1.00'),
            price=Decimal('10.00')
        )

        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '(Archived)')

    def test_job_detail_shows_archived_indicator(self):
        """Test that job detail shows (Archived) for archived price list items."""
        # Create line item with archived price list item
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            price_list_item=self.archived_item,
            description='Line with archived item',
            qty=Decimal('1.00'),
            price=Decimal('20.00')
        )

        # Set estimate as current
        self.job.current_estimate = self.estimate
        self.job.save()

        response = self.client.get(
            reverse('jobs:detail', args=[self.job.job_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '(Archived)')


class PriceListItemArchiveIntegrationTest(TestCase):
    """Integration tests for the full archive workflow."""

    def setUp(self):
        self.client = Client()

    def test_create_archive_restore_workflow(self):
        """Test full workflow: create item, archive it, restore it."""
        # 1. Create a new item via form
        response = self.client.post(
            reverse('invoicing:price_list_item_add'),
            {
                'code': 'WORKFLOW001',
                'description': 'Workflow Test Item',
                'selling_price': '50.00',
                'purchase_price': '25.00',
                'qty_on_hand': '100.00',
                'qty_sold': '0.00',
                'qty_wasted': '0.00',
            }
        )
        self.assertRedirects(response, reverse('invoicing:price_list_item_list'))

        item = PriceListItem.objects.get(code='WORKFLOW001')
        self.assertTrue(item.is_active)

        # 2. Archive the item via edit form
        response = self.client.post(
            reverse('invoicing:price_list_item_edit', args=[item.price_list_item_id]),
            {
                'code': 'WORKFLOW001',
                'description': 'Workflow Test Item',
                'selling_price': '50.00',
                'purchase_price': '25.00',
                'qty_on_hand': '100.00',
                'qty_sold': '0.00',
                'qty_wasted': '0.00',
                # is_active not included = False (unchecked checkbox)
            }
        )
        self.assertRedirects(response, reverse('invoicing:price_list_item_list'))

        item.refresh_from_db()
        self.assertFalse(item.is_active)

        # 3. Verify it doesn't show in default list
        response = self.client.get(reverse('invoicing:price_list_item_list'))
        self.assertNotContains(response, 'WORKFLOW001')

        # 4. Verify it shows in archived list
        response = self.client.get(
            reverse('invoicing:price_list_item_list') + '?show_archived=1'
        )
        self.assertContains(response, 'WORKFLOW001')

        # 5. Restore the item
        response = self.client.post(
            reverse('invoicing:price_list_item_edit', args=[item.price_list_item_id]),
            {
                'code': 'WORKFLOW001',
                'description': 'Workflow Test Item',
                'selling_price': '50.00',
                'purchase_price': '25.00',
                'qty_on_hand': '100.00',
                'qty_sold': '0.00',
                'qty_wasted': '0.00',
                'is_active': 'on',  # Checkbox checked
            }
        )
        self.assertRedirects(response, reverse('invoicing:price_list_item_list'))

        item.refresh_from_db()
        self.assertTrue(item.is_active)

        # 6. Verify it shows in default list again
        response = self.client.get(reverse('invoicing:price_list_item_list'))
        self.assertContains(response, 'WORKFLOW001')

    def test_archived_item_not_selectable_in_forms(self):
        """Test that archived items can't be selected when adding line items."""
        # Create and archive an item
        item = PriceListItem.objects.create(
            code='NOTSELECTABLE',
            description='Not Selectable Item',
            selling_price=Decimal('10.00'),
            is_active=False
        )

        # Create estimate to add line items to
        contact = Contact.objects.create(
            first_name='Test',
            last_name='User',
            email='test@example.com'
        )
        job = Job.objects.create(job_number='TEST-002', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-TEST-002',
            status='draft'
        )

        # Try to add line item with archived price list item
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'pricelist_submit': '1',
                'price_list_item': item.price_list_item_id,
                'qty': '5.00',
            }
        )

        # The form should reject the archived item
        # (it's not in the queryset, so validation should fail)
        self.assertEqual(response.status_code, 200)  # Form redisplayed with error
        self.assertEqual(EstimateLineItem.objects.filter(estimate=estimate).count(), 0)
