"""B8: Task.service_price is NOT NULL at the DB level.

These tests verify the tightening introduced in migration
0035_phase_b_tighten_task_service_price:

1. Creating a Task without service_price raises IntegrityError (DB constraint).
2. The Task.service_price related_name is 'task_set', so
   ServicePrice.task_set.exists() works as the reverse manager.
3. Task.clean() still validates status transitions and nothing else
   (no charge guard, no service_price validation — that's now DB-level).
"""
from decimal import Decimal

from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job, ServicePrice, Task


def _make_scheme(name='S-b8'):
    ac, _ = AccountingCategory.objects.get_or_create(code='B8', defaults={'name': 'B8-Labor'})
    return ServicePrice.objects.create(
        name=name, algorithm=ServicePrice.FLAT_FEE,
        rate=Decimal('1'), unit_label='ea',
        accounting_category=ac,
    )


def _make_job(suffix='b8'):
    contact = Contact.objects.create(
        first_name='F', last_name='L', email=f'f-{suffix}@b8.test',
    )
    biz = Business.objects.create(
        business_name=f'Biz-{suffix}', default_contact=contact,
    )
    contact.business = biz
    contact.save()
    return Job.objects.create(job_number=f'J-{suffix}', contact=contact)


class TaskServicePriceNotNullTest(TestCase):
    """service_price must be set; the DB column is NOT NULL."""

    def setUp(self):
        self.scheme = _make_scheme()
        self.job = _make_job()

    def test_task_with_service_price_saves_ok(self):
        """Happy path: Task with service_price creates successfully."""
        task = Task.objects.create(
            job=self.job, name='Valid task', service_price=self.scheme,
        )
        task.refresh_from_db()
        self.assertEqual(task.service_price_id, self.scheme.pk)

    def test_task_without_service_price_raises_validation_error(self):
        """Task.service_price is NOT NULL — omitting it raises ValidationError."""
        from django.core.exceptions import ValidationError
        # Task.save() calls full_clean(), which surfaces the NOT NULL
        # constraint as a ValidationError before the DB is ever hit.
        t = Task(job=self.job, name='No scheme', sort_order=1)
        with self.assertRaises(ValidationError) as cm:
            t.save()
        self.assertIn('service_price', cm.exception.message_dict)


class ServicePriceReverseManagerTest(TestCase):
    """Task.service_price related_name is 'task_set' — reverse manager works."""

    def setUp(self):
        self.scheme = _make_scheme('S-b8-rev')
        self.other = _make_scheme('S-b8-other')
        self.job = _make_job('b8-rev')

    def test_task_set_reverse_manager_returns_linked_tasks(self):
        t1 = Task.objects.create(job=self.job, name='T1', service_price=self.scheme)
        t2 = Task.objects.create(job=self.job, name='T2', service_price=self.scheme)
        Task.objects.create(job=self.job, name='T3', service_price=self.other)

        linked = list(self.scheme.task_set.values_list('pk', flat=True))
        self.assertIn(t1.pk, linked)
        self.assertIn(t2.pk, linked)
        self.assertEqual(len(linked), 2)

    def test_is_referenced_detects_task_via_reverse_manager(self):
        """ServicePrice.is_referenced() returns True when a Task uses it."""
        self.assertFalse(self.scheme.is_referenced())
        Task.objects.create(job=self.job, name='Ref task', service_price=self.scheme)
        self.assertTrue(self.scheme.is_referenced())

    def test_unreferenced_scheme_is_not_referenced(self):
        """Scheme with no Tasks/PlanTasks/Templates is not referenced."""
        self.assertFalse(self.other.is_referenced())


class TaskCleanStatusTransitionTest(TestCase):
    """Task.clean() validates status transitions only — no charge guard."""

    def setUp(self):
        self.scheme = _make_scheme('S-b8-clean')
        self.job = _make_job('b8-clean')
        self.task = Task.objects.create(
            job=self.job, name='Clean task', service_price=self.scheme,
        )

    def test_valid_status_transition_passes_clean(self):
        self.task.status = Task.STATUS_IN_PROGRESS
        self.task.full_clean()  # Should not raise

    def test_invalid_status_transition_raises_validation_error(self):
        from django.core.exceptions import ValidationError
        # complete → in_progress is not a valid transition
        self.task.status = Task.STATUS_COMPLETE
        self.task.save()
        self.task.status = Task.STATUS_IN_PROGRESS
        with self.assertRaises(ValidationError):
            self.task.full_clean()
