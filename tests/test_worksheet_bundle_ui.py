"""Tests for worksheet-level bundle editing UI."""
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from apps.jobs.models import Task, TaskBundle, EstWorksheet, Job
from apps.contacts.models import Contact, Business
from apps.core.models import User, LineItemType


class WorksheetBundleUITestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@test.com', password='testpass123'
        )
        self.client.force_login(self.user)

        self.default_contact = Contact.objects.create(
            first_name='Default', last_name='Contact', email='dc@test.com'
        )
        self.business = Business.objects.create(
            business_name='Test Co', business_phone='123-456',
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
        self.lit_labor, _ = LineItemType.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.task1 = Task.objects.create(
            est_worksheet=self.worksheet, name='Sand Floor',
            rate=Decimal('50'), est_qty=Decimal('1'), units='hours'
        )
        self.task2 = Task.objects.create(
            est_worksheet=self.worksheet, name='Clean Floor',
            rate=Decimal('25'), est_qty=Decimal('1'), units='hours'
        )
        self.task3 = Task.objects.create(
            est_worksheet=self.worksheet, name='Apply Finish',
            rate=Decimal('100'), est_qty=Decimal('2'), units='hours'
        )


class WorksheetBundleCreationTest(WorksheetBundleUITestBase):

    def test_bundle_selected_tasks(self):
        """POSTing bundle_tasks creates a TaskBundle and assigns selected tasks."""
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url, {
            'bundle_tasks': '',
            'selected_tasks': [self.task1.task_id, self.task2.task_id],
            'bundle_name': 'Prep Work',
            'bundle_description': 'Floor preparation',
            'line_item_type': self.lit_labor.pk,
        })
        self.assertEqual(response.status_code, 302)

        # TaskBundle should exist
        bundles = list(self.worksheet.bundles.all())
        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0].name, 'Prep Work')
        self.assertEqual(bundles[0].line_item_type, self.lit_labor)

        # Tasks should be bundled
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()
        self.task3.refresh_from_db()
        self.assertEqual(self.task1.mapping_strategy, 'bundle')
        self.assertEqual(self.task1.bundle, bundles[0])
        self.assertEqual(self.task2.mapping_strategy, 'bundle')
        self.assertEqual(self.task2.bundle, bundles[0])
        # task3 unchanged
        self.assertEqual(self.task3.mapping_strategy, 'direct')
        self.assertIsNone(self.task3.bundle)

    def test_bundle_requires_two_tasks(self):
        """Bundling fewer than 2 tasks shows error."""
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url, {
            'bundle_tasks': '',
            'selected_tasks': [self.task1.task_id],
            'bundle_name': 'Too Small',
            'line_item_type': self.lit_labor.pk,
        }, follow=True)
        self.assertEqual(self.worksheet.bundles.count(), 0)

    def test_bundle_requires_name(self):
        """Bundling without a name shows error."""
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        self.client.post(url, {
            'bundle_tasks': '',
            'selected_tasks': [self.task1.task_id, self.task2.task_id],
            'bundle_name': '',
            'line_item_type': self.lit_labor.pk,
        })
        self.assertEqual(self.worksheet.bundles.count(), 0)


class WorksheetUnbundleTest(WorksheetBundleUITestBase):

    def setUp(self):
        super().setUp()
        self.bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            line_item_type=self.lit_labor, sort_order=1
        )
        self.task1.mapping_strategy = 'bundle'
        self.task1.bundle = self.bundle
        self.task1.save()
        self.task2.mapping_strategy = 'bundle'
        self.task2.bundle = self.bundle
        self.task2.save()

    def test_unbundle_task(self):
        """Removing a task from a bundle sets it to direct."""
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url, {
            'remove_task': self.task1.task_id,
        })
        self.assertEqual(response.status_code, 302)

        self.task1.refresh_from_db()
        self.assertEqual(self.task1.mapping_strategy, 'direct')
        self.assertIsNone(self.task1.bundle)

    def test_unbundle_last_two_dissolves_bundle(self):
        """Unbundling a task when only 2 remain dissolves the bundle entirely."""
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        self.client.post(url, {'remove_task': self.task1.task_id})

        # Only 1 task left in bundle -> auto-dissolve
        self.task2.refresh_from_db()
        self.assertEqual(self.task2.mapping_strategy, 'direct')
        self.assertIsNone(self.task2.bundle)
        self.assertEqual(self.worksheet.bundles.count(), 0)


class WorksheetBundleReorderTest(WorksheetBundleUITestBase):

    def test_container_level_reorder(self):
        """Reordering at container level swaps sort_order between a bundle and an unbundled task."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            line_item_type=self.lit_labor, sort_order=1
        )
        self.task1.mapping_strategy = 'bundle'
        self.task1.bundle = bundle
        self.task1.sort_order = 1
        self.task1.save()
        self.task2.mapping_strategy = 'bundle'
        self.task2.bundle = bundle
        self.task2.sort_order = 2
        self.task2.save()
        self.task3.sort_order = 2
        self.task3.save()

        # Move bundle down (swap with task3)
        url = reverse('jobs:worksheet_reorder_item', args=[
            self.worksheet.est_worksheet_id, 'bundle', bundle.pk, 'down'
        ])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        bundle.refresh_from_db()
        self.task3.refresh_from_db()
        self.assertEqual(bundle.sort_order, 2)
        self.assertEqual(self.task3.sort_order, 1)

    def test_within_bundle_reorder(self):
        """Reordering within a bundle swaps sort_order of two bundled tasks."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Prep',
            line_item_type=self.lit_labor, sort_order=1
        )
        self.task1.mapping_strategy = 'bundle'
        self.task1.bundle = bundle
        self.task1.sort_order = 1
        self.task1.save()
        self.task2.mapping_strategy = 'bundle'
        self.task2.bundle = bundle
        self.task2.sort_order = 2
        self.task2.save()

        # Move task1 down within bundle
        url = reverse('jobs:worksheet_reorder_in_bundle', args=[
            self.worksheet.est_worksheet_id, self.task1.task_id, 'down'
        ])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.task1.refresh_from_db()
        self.task2.refresh_from_db()
        self.assertEqual(self.task1.sort_order, 2)
        self.assertEqual(self.task2.sort_order, 1)
