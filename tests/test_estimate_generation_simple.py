from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.contacts.models import Contact, Business
from apps.core.models import Configuration
from apps.jobs.models import (
    Job, EstWorksheet, Task, TaskMapping, EstimateLineItem, ProductBundlingRule,
    TaskTemplate, TaskInstanceMapping
)
from apps.jobs.services import EstimateGenerationService


User = get_user_model()


class SimpleEstimateGenerationTestCase(TestCase):
    """Simple tests to verify basic functionality works"""

    def setUp(self):
        """Set up minimal test data"""
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

        # Create contact first for default_contact
        self.contact = Contact.objects.create(
            first_name='Test Customer',
            last_name='',
            email='customer@example.com'
        )

        self.business = Business.objects.create(
            business_name='Test Company',
            business_address='123 Test St',
            default_contact=self.contact
        )

        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='TEST-001',
            contact=self.contact,
            description='Test Job'
        )

        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft'
        )

        self.service = EstimateGenerationService()
    
    def test_direct_mapping_basic(self):
        """Test a single task with direct mapping"""
        # Create mapping template
        mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='direct',
            task_type_id='test',
            line_item_description='Test task description'
        )
        
        # Create task template
        template = TaskTemplate.objects.create(
            template_name='Test Task Template',
            task_mapping=mapping
        )
        
        # Create task
        task = Task.objects.create(
            est_worksheet=self.worksheet,
            template=template,
            name='Test Task',
            units='hours',
            rate=Decimal('100.00'),
            est_qty=Decimal('5.00')
        )
        
        # Generate estimate
        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)
        
        # Verify
        self.assertIsNotNone(estimate)
        line_items = estimate.estimatelineitem_set.all()
        self.assertEqual(line_items.count(), 1)
        
        line_item = line_items.first()
        self.assertEqual(line_item.description, 'Test task description')
        self.assertEqual(line_item.qty, Decimal('5.00'))
        self.assertEqual(line_item.price_currency, Decimal('500.00'))
    
    def test_task_without_mapping_defaults_direct(self):
        """Test task without mapping uses direct strategy"""
        # Create task without template/mapping
        task = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Unmapped Task',
            units='each',
            rate=Decimal('200.00'),
            est_qty=Decimal('2.00')
        )
        
        # Generate estimate
        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)
        
        # Verify
        line_items = estimate.estimatelineitem_set.all()
        self.assertEqual(line_items.count(), 1)
        
        line_item = line_items.first()
        self.assertEqual(line_item.description, 'Unmapped Task')
        self.assertEqual(line_item.qty, Decimal('2.00'))
        self.assertEqual(line_item.price_currency, Decimal('400.00'))
    
    def test_excluded_task(self):
        """Test that excluded tasks don't appear in estimate"""
        # Create visible task mapping and template
        visible_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='direct',
            task_type_id='visible'
        )
        visible_template = TaskTemplate.objects.create(
            template_name='Visible Task Template',
            task_mapping=visible_mapping
        )
        visible_task = Task.objects.create(
            est_worksheet=self.worksheet,
            template=visible_template,
            name='Visible Task',
            units='hours',
            rate=Decimal('100.00'),
            est_qty=Decimal('3.00')
        )
        
        # Create excluded task mapping and template
        excluded_mapping = TaskMapping.objects.create(
            step_type='overhead',
            mapping_strategy='exclude',
            task_type_id='internal'
        )
        excluded_template = TaskTemplate.objects.create(
            template_name='Internal Task Template',
            task_mapping=excluded_mapping
        )
        excluded_task = Task.objects.create(
            est_worksheet=self.worksheet,
            template=excluded_template,
            name='Internal Task',
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00')
        )
        
        # Generate estimate
        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)
        
        # Verify only visible task appears
        line_items = estimate.estimatelineitem_set.all()
        self.assertEqual(line_items.count(), 1)
        
        line_item = line_items.first()
        self.assertEqual(line_item.description, 'Visible Task')
        self.assertEqual(line_item.price_currency, Decimal('300.00'))
    
    def test_product_bundle_basic(self):
        """Test basic product bundling"""
        # Create design mapping and template
        design_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='bundle_to_product',
            default_product_type='table',
            task_type_id='design'
        )
        design_template = TaskTemplate.objects.create(
            template_name='Design Work Template',
            task_mapping=design_mapping
        )
        
        # Create build mapping and template
        build_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='bundle_to_product',
            default_product_type='table',
            task_type_id='build'
        )
        build_template = TaskTemplate.objects.create(
            template_name='Build Work Template',
            task_mapping=build_mapping
        )
        
        # Create tasks for a product
        task1 = Task.objects.create(
            est_worksheet=self.worksheet,
            template=design_template,
            name='Design Work',
            units='hours',
            rate=Decimal('150.00'),
            est_qty=Decimal('4.00')
        )
        
        task2 = Task.objects.create(
            est_worksheet=self.worksheet,
            template=build_template,
            name='Build Work',
            units='hours',
            rate=Decimal('100.00'),
            est_qty=Decimal('8.00')
        )
        
        # Create instance mappings with same product identifier
        TaskInstanceMapping.objects.create(
            task=task1,
            product_identifier='table_001'
        )
        TaskInstanceMapping.objects.create(
            task=task2,
            product_identifier='table_001'
        )
        
        # Create bundling rule
        ProductBundlingRule.objects.create(
            rule_name='Table Rule',
            product_type='table',
            line_item_template='Custom Table',
            pricing_method='sum_components'
        )
        
        # Generate estimate
        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)
        
        # Verify single bundled line item
        line_items = estimate.estimatelineitem_set.all()
        self.assertEqual(line_items.count(), 1)
        
        line_item = line_items.first()
        self.assertEqual(line_item.description, 'Custom Table')
        self.assertEqual(line_item.qty, Decimal('1.00'))
        # Total: (4*150) + (8*100) = 600 + 800 = 1400
        self.assertEqual(line_item.price_currency, Decimal('1400.00'))
    
    def test_service_bundle_basic(self):
        """Test basic service bundling"""
        # Create setup mapping and template
        setup_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='bundle_to_service',
            default_product_type='installation_service',
            task_type_id='setup'
        )
        setup_template = TaskTemplate.objects.create(
            template_name='Setup Template',
            task_mapping=setup_mapping
        )
        
        # Create installation mapping and template
        install_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='bundle_to_service',
            default_product_type='installation_service',
            task_type_id='install'
        )
        install_template = TaskTemplate.objects.create(
            template_name='Installation Template',
            task_mapping=install_mapping
        )
        
        # Create service tasks
        task1 = Task.objects.create(
            est_worksheet=self.worksheet,
            template=setup_template,
            name='Setup',
            units='hours',
            rate=Decimal('75.00'),
            est_qty=Decimal('2.00')
        )
        
        task2 = Task.objects.create(
            est_worksheet=self.worksheet,
            template=install_template,
            name='Installation',
            units='hours',
            rate=Decimal('100.00'),
            est_qty=Decimal('3.00')
        )
        
        # Generate estimate
        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)
        
        # Verify service bundle line item
        line_items = estimate.estimatelineitem_set.all()
        self.assertEqual(line_items.count(), 1)
        
        line_item = line_items.first()
        self.assertIn('Installation Service', line_item.description)
        self.assertIn('Setup', line_item.description)
        self.assertIn('Installation', line_item.description)
        self.assertEqual(line_item.qty, Decimal('5.00'))  # 2 + 3 hours
        # Total: (2*75) + (3*100) = 150 + 300 = 450
        self.assertEqual(line_item.price_currency, Decimal('450.00'))