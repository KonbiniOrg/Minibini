from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Task, TaskBundle, EstWorksheet, WorkOrder, Job
from apps.contacts.models import Contact, Business
from apps.core.models import LineItemType


class TaskBundleTestBase(TestCase):
    """Shared setup for TaskBundle tests."""

    def setUp(self):
        self.default_contact = Contact.objects.create(
            first_name='Default', last_name='Contact', email='default@test.com'
        )
        self.business = Business.objects.create(
            business_name='Test Co',
            business_phone='123-456-7890',
            default_contact=self.default_contact
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User', email='test@test.com',
            business=self.business
        )
        self.job = Job.objects.create(
            job_number='JOB-001', name='Test Job',
            contact=self.contact, status='draft'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.work_order = WorkOrder.objects.create(
            job=self.job, status='incomplete'
        )
        self.line_item_type, _ = LineItemType.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': True}
        )


class TaskBundleModelTest(TaskBundleTestBase):
    """Tests for the TaskBundle model."""

    def test_create_bundle_on_worksheet(self):
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet,
            name='Prep Work',
            line_item_type=self.line_item_type,
            sort_order=1
        )
        self.assertEqual(bundle.get_container(), self.worksheet)
        self.assertIsNone(bundle.work_order)

    def test_create_bundle_on_work_order(self):
        bundle = TaskBundle.objects.create(
            work_order=self.work_order,
            name='Prep Work',
            line_item_type=self.line_item_type,
            sort_order=1
        )
        self.assertEqual(bundle.get_container(), self.work_order)
        self.assertIsNone(bundle.est_worksheet)

    def test_bundle_requires_exactly_one_container(self):
        """Bundle with both containers should fail validation."""
        bundle = TaskBundle(
            est_worksheet=self.worksheet,
            work_order=self.work_order,
            name='Bad Bundle',
            line_item_type=self.line_item_type
        )
        with self.assertRaises(ValidationError):
            bundle.full_clean()

    def test_bundle_requires_at_least_one_container(self):
        """Bundle with no container should fail validation."""
        bundle = TaskBundle(
            name='Orphan Bundle',
            line_item_type=self.line_item_type
        )
        with self.assertRaises(ValidationError):
            bundle.full_clean()

    def test_bundle_ordering(self):
        """Bundles should be ordered by sort_order then name."""
        b2 = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='B Bundle',
            line_item_type=self.line_item_type, sort_order=2
        )
        b1 = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='A Bundle',
            line_item_type=self.line_item_type, sort_order=1
        )
        bundles = list(self.worksheet.bundles.all())
        self.assertEqual(bundles, [b1, b2])

    def test_bundle_str(self):
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet,
            name='Prep Work',
            line_item_type=self.line_item_type
        )
        self.assertIn('Prep Work', str(bundle))


class TaskMappingFieldsTest(TaskBundleTestBase):
    """Tests for Task's mapping_strategy and bundle fields."""

    def test_default_mapping_strategy_is_direct(self):
        task = Task.objects.create(
            est_worksheet=self.worksheet, name='Test Task'
        )
        self.assertEqual(task.mapping_strategy, 'direct')
        self.assertIsNone(task.bundle)

    def test_task_with_bundle(self):
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            line_item_type=self.line_item_type, sort_order=1
        )
        task = Task.objects.create(
            est_worksheet=self.worksheet, name='Sand Floor',
            mapping_strategy='bundle', bundle=bundle
        )
        self.assertEqual(task.bundle, bundle)
        self.assertEqual(task.mapping_strategy, 'bundle')
        self.assertIn(task, bundle.tasks.all())

    def test_exclude_mapping_strategy(self):
        task = Task.objects.create(
            est_worksheet=self.worksheet, name='Internal Task',
            mapping_strategy='exclude'
        )
        self.assertEqual(task.mapping_strategy, 'exclude')

    def test_bundled_task_requires_bundle(self):
        """mapping_strategy='bundle' without a bundle should fail."""
        task = Task(
            est_worksheet=self.worksheet, name='Bad Task',
            mapping_strategy='bundle', bundle=None
        )
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_bundle_fk_requires_bundle_strategy(self):
        """Task with a bundle FK but non-bundle strategy should fail."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            line_item_type=self.line_item_type
        )
        task = Task(
            est_worksheet=self.worksheet, name='Bad Task',
            mapping_strategy='direct', bundle=bundle
        )
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_bundle_set_null_on_delete(self):
        """Deleting a TaskBundle should null out the FK on tasks, not cascade."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            line_item_type=self.line_item_type
        )
        task = Task.objects.create(
            est_worksheet=self.worksheet, name='Sand Floor',
            mapping_strategy='bundle', bundle=bundle
        )
        bundle.delete()
        task.refresh_from_db()
        self.assertIsNone(task.bundle)

    def test_multiple_tasks_in_bundle(self):
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            line_item_type=self.line_item_type
        )
        t1 = Task.objects.create(
            est_worksheet=self.worksheet, name='Sand Floor',
            mapping_strategy='bundle', bundle=bundle
        )
        t2 = Task.objects.create(
            est_worksheet=self.worksheet, name='Clean Floor',
            mapping_strategy='bundle', bundle=bundle
        )
        self.assertEqual(set(bundle.tasks.all()), {t1, t2})
