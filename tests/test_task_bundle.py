from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import PlanTask, PlanBundle, Job
from apps.estimates.models import EstWorksheet
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class PlanBundleTestBase(TestCase):
    """Shared setup for PlanBundle tests."""

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
            contact=self.contact, status=Job.STATUS_DRAFT
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status=Job.STATUS_DRAFT, version=1
        )
        self.accounting_category, _ = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': True}
        )


class PlanBundleModelTest(PlanBundleTestBase):
    """Tests for the PlanBundle model."""

    def test_create_bundle_on_worksheet(self):
        bundle = PlanBundle.objects.create(
            est_worksheet=self.worksheet,
            name='Prep Work',
            accounting_category=self.accounting_category,
            sort_order=1
        )
        self.assertEqual(bundle.est_worksheet, self.worksheet)

    def test_bundle_ordering(self):
        """Bundles should be ordered by sort_order then name."""
        b2 = PlanBundle.objects.create(
            est_worksheet=self.worksheet, name='B Bundle',
            accounting_category=self.accounting_category, sort_order=2
        )
        b1 = PlanBundle.objects.create(
            est_worksheet=self.worksheet, name='A Bundle',
            accounting_category=self.accounting_category, sort_order=1
        )
        bundles = list(self.worksheet.plan_bundles.all())
        self.assertEqual(bundles, [b1, b2])

    def test_bundle_str(self):
        bundle = PlanBundle.objects.create(
            est_worksheet=self.worksheet,
            name='Prep Work',
            accounting_category=self.accounting_category
        )
        self.assertIn('Prep Work', str(bundle))


class PlanTaskMappingFieldsTest(PlanBundleTestBase):
    """Tests for PlanTask's mapping_strategy and bundle fields."""

    def test_default_mapping_strategy_is_direct(self):
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Test Task'
        )
        self.assertEqual(task.mapping_strategy, 'direct')
        self.assertIsNone(task.bundle)

    def test_task_with_bundle(self):
        bundle = PlanBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            accounting_category=self.accounting_category, sort_order=1
        )
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Sand Floor',
            mapping_strategy='bundle', bundle=bundle
        )
        self.assertEqual(task.bundle, bundle)
        self.assertEqual(task.mapping_strategy, 'bundle')
        self.assertIn(task, bundle.plan_tasks.all())

    def test_exclude_mapping_strategy(self):
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Internal Task',
            mapping_strategy='exclude'
        )
        self.assertEqual(task.mapping_strategy, 'exclude')

    def test_bundled_task_requires_bundle(self):
        """mapping_strategy='bundle' without a bundle should fail."""
        task = PlanTask(
            est_worksheet=self.worksheet, name='Bad Task',
            mapping_strategy='bundle', bundle=None
        )
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_bundle_fk_requires_bundle_strategy(self):
        """PlanTask with a bundle FK but non-bundle strategy should fail."""
        bundle = PlanBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            accounting_category=self.accounting_category
        )
        task = PlanTask(
            est_worksheet=self.worksheet, name='Bad Task',
            mapping_strategy='direct', bundle=bundle
        )
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_bundle_set_null_on_delete(self):
        """Deleting a PlanBundle should null out the FK on plan tasks, not cascade."""
        bundle = PlanBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            accounting_category=self.accounting_category
        )
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Sand Floor',
            mapping_strategy='bundle', bundle=bundle
        )
        bundle.delete()
        task.refresh_from_db()
        self.assertIsNone(task.bundle)

    def test_multiple_tasks_in_bundle(self):
        bundle = PlanBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            accounting_category=self.accounting_category
        )
        t1 = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Sand Floor',
            mapping_strategy='bundle', bundle=bundle
        )
        t2 = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Clean Floor',
            mapping_strategy='bundle', bundle=bundle
        )
        self.assertEqual(set(bundle.plan_tasks.all()), {t1, t2})
