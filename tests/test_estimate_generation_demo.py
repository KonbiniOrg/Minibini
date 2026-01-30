from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.contacts.models import Contact, Business
from apps.core.models import Configuration
from apps.jobs.models import (
    Job, EstWorksheet, Task, TaskMapping, ProductBundlingRule, EstimateLineItem,
    TaskTemplate, TaskInstanceMapping
)
from apps.jobs.services import EstimateGenerationService


User = get_user_model()


class EstimateGenerationDemoTestCase(TestCase):
    """Demo test showing complete EstWorksheet to Estimate conversion functionality"""

    def test_comprehensive_estimate_generation_demo(self):
        """Test comprehensive scenario with all mapping types"""

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        # Create test data
        # Create contact first for default_contact
        contact = Contact.objects.create(first_name='Demo Customer', last_name='', email='demo.customer@test.com')
        business = Business.objects.create(
            business_name='Demo Company',
            default_contact=contact
        )
        contact.business = business
        contact.save()
        job = Job.objects.create(job_number='DEMO-001', contact=contact)
        worksheet = EstWorksheet.objects.create(job=job, status='draft')

        # Create tasks with different mapping strategies
        # 1. Direct mapping task
        direct_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='direct',
            task_type_id='consultation',
            line_item_description='Initial project consultation and planning'
        )
        direct_template = TaskTemplate.objects.create(
            template_name='Project Consultation Template',
            task_mapping=direct_mapping
        )
        direct_task = Task.objects.create(
            est_worksheet=worksheet,
            template=direct_template,
            name='Project Consultation',
            units='hours',
            rate=Decimal('150.00'),
            est_qty=Decimal('4.00')
        )

        # 2. Product bundle tasks (table)
        table_tasks = [
            ('Table Design', 'labor', 'hours', '150.00', '6.00'),
            ('Wood Materials', 'material', 'board_feet', '30.00', '40.00'),
            ('Table Assembly', 'labor', 'hours', '100.00', '8.00'),
        ]

        for name, step_type, units, rate, qty in table_tasks:
            # Create mapping and template for each task type
            mapping = TaskMapping.objects.create(
                step_type=step_type,
                mapping_strategy='bundle_to_product',
                default_product_type='table',
                task_type_id=name.lower().replace(' ', '_')
            )
            template = TaskTemplate.objects.create(
                template_name=f'{name} Template',
                task_mapping=mapping
            )
            task = Task.objects.create(
                est_worksheet=worksheet,
                template=template,
                name=name,
                units=units,
                rate=Decimal(rate),
                est_qty=Decimal(qty)
            )
            # Create instance mapping to group tasks into same product
            TaskInstanceMapping.objects.create(
                task=task,
                product_identifier='table_001'
            )

        # 3. Service bundle tasks
        service_tasks = [
            ('Delivery Setup', 'delivery', '75.00', '2.00'),
            ('Installation', 'delivery', '100.00', '3.00'),
        ]

        for name, service_type, rate, qty in service_tasks:
            # Create mapping and template for each service task
            mapping = TaskMapping.objects.create(
                step_type='labor',
                mapping_strategy='bundle_to_service',
                default_product_type=service_type,
                task_type_id=name.lower().replace(' ', '_')
            )
            template = TaskTemplate.objects.create(
                template_name=f'{name} Template',
                task_mapping=mapping
            )
            task = Task.objects.create(
                est_worksheet=worksheet,
                template=template,
                name=name,
                units='hours',
                rate=Decimal(rate),
                est_qty=Decimal(qty)
            )

        # 4. Excluded task (internal)
        excluded_mapping = TaskMapping.objects.create(
            step_type='overhead',
            mapping_strategy='exclude',
            task_type_id='qa_review'
        )
        excluded_template = TaskTemplate.objects.create(
            template_name='Internal Quality Review Template',
            task_mapping=excluded_mapping
        )
        excluded_task = Task.objects.create(
            est_worksheet=worksheet,
            template=excluded_template,
            name='Internal Quality Review',
            units='hours',
            rate=Decimal('80.00'),
            est_qty=Decimal('2.00')
        )

        # Create bundling rule for table
        ProductBundlingRule.objects.create(
            rule_name='Table Bundling Rule',
            product_type='table',
            line_item_template='Custom Dining Table',
            pricing_method='sum_components',
            include_materials=True,
            include_labor=True
        )

        # Generate estimate
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Verify estimate was created
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.job, job)
        self.assertEqual(estimate.status, 'draft')

        # Display and verify results
        line_items = estimate.estimatelineitem_set.all().order_by('line_number')

        # Should have 3 line items (direct + product bundle + service bundle, excluded not included)
        self.assertEqual(line_items.count(), 3)

        total = Decimal('0.00')
        line_descriptions = []

        for i, item in enumerate(line_items, 1):
            line_descriptions.append(item.description)
            if item.qty > 0:
                unit_price = item.price_currency / item.qty
            total += item.price_currency

        # Verify specific line items exist
        self.assertTrue(any('Initial project consultation' in desc for desc in line_descriptions))
        self.assertTrue(any('Custom Dining Table' in desc for desc in line_descriptions))
        self.assertTrue(any('Delivery' in desc for desc in line_descriptions))

        # Verify excluded task is NOT in estimate
        self.assertFalse(any('Quality Review' in desc for desc in line_descriptions))

        # Verify pricing calculations
        # Direct task: 4 * 150 = 600
        # Table bundle: (6*150) + (40*30) + (8*100) = 900 + 1200 + 800 = 2900
        # Service bundle: (2*75) + (3*100) = 150 + 300 = 450
        # Total expected: 600 + 2900 + 450 = 3950
        expected_total = Decimal('3950.00')
        self.assertEqual(total, expected_total)

        tasks = worksheet.task_set.all()
        mapping_strategies = []
        for task in tasks:
            strategy = task.get_mapping_strategy()
            step_type = task.get_step_type()
            mapping_strategies.append(strategy)

        # Verify all mapping strategies were used
        self.assertIn('direct', mapping_strategies)
        self.assertIn('bundle_to_product', mapping_strategies)
        self.assertIn('bundle_to_service', mapping_strategies)
        self.assertIn('exclude', mapping_strategies)

        # Additional detailed verifications
        direct_item = next(item for item in line_items if 'consultation' in item.description)
        self.assertEqual(direct_item.qty, Decimal('4.00'))
        self.assertEqual(direct_item.price_currency, Decimal('600.00'))

        table_item = next(item for item in line_items if 'Table' in item.description)
        self.assertEqual(table_item.qty, Decimal('1.00'))
        self.assertEqual(table_item.price_currency, Decimal('2900.00'))

        service_item = next(item for item in line_items if 'Delivery' in item.description)
        self.assertEqual(service_item.qty, Decimal('5.00'))  # 2 + 3 hours
        self.assertEqual(service_item.price_currency, Decimal('450.00'))