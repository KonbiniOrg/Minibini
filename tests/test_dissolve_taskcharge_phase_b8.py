"""B8 (historical): originally verified Task.rate_scheme was NOT NULL at the
DB level (migration 0035_phase_b_tighten_task_rate_scheme). Task-owned-money
Phase 1 removed that FK-required invariant entirely: Task's provenance FK
(now source_scheme) is nullable/SET_NULL and pricing lives on the task's own
qty_source/rate/unit_label/accounting_category fields — so the NOT-NULL
class that used to live here (TaskRateSchemeNotNullTest) was deleted rather
than repaired; it tested a constraint that no longer exists by design.

What's left:

1. The RateScheme reverse manager (related_name is now 'stamped_tasks', not
   'task_set') and RateScheme.is_referenced().
2. Task.clean() still validates status transitions and nothing else
   (no charge guard, no rate_scheme validation).
"""
from decimal import Decimal

from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job, RateScheme, Task


def _make_scheme(name='S-b8'):
    ac, _ = AccountingCategory.objects.get_or_create(code='B8', defaults={'name': 'B8-Labor'})
    return RateScheme.objects.create(
        name=name, algorithm=RateScheme.ENTERED_QTY,
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


class RateSchemeReverseManagerTest(TestCase):
    """RateScheme.stamped_tasks (source_scheme's related_name) reverse
    manager works."""

    def setUp(self):
        self.scheme = _make_scheme('S-b8-rev')
        self.other = _make_scheme('S-b8-other')
        self.job = _make_job('b8-rev')

    def _stamped(self, name, scheme):
        t = Task(job=self.job, name=name)
        t.stamp_from_scheme(scheme)
        t.save()
        return t

    def test_stamped_tasks_reverse_manager_returns_linked_tasks(self):
        t1 = self._stamped('T1', self.scheme)
        t2 = self._stamped('T2', self.scheme)
        self._stamped('T3', self.other)

        linked = list(self.scheme.stamped_tasks.values_list('pk', flat=True))
        self.assertIn(t1.pk, linked)
        self.assertIn(t2.pk, linked)
        self.assertEqual(len(linked), 2)

    def test_is_referenced_detects_task_via_reverse_manager(self):
        """RateScheme.is_referenced() returns True when a Task uses it."""
        self.assertFalse(self.scheme.is_referenced())
        self._stamped('Ref task', self.scheme)
        self.assertTrue(self.scheme.is_referenced())

    def test_unreferenced_scheme_is_not_referenced(self):
        """Scheme with no Tasks/Templates is not referenced."""
        self.assertFalse(self.other.is_referenced())


class TaskCleanStatusTransitionTest(TestCase):
    """Task.clean() validates status transitions only — no charge guard."""

    def setUp(self):
        self.scheme = _make_scheme('S-b8-clean')
        self.job = _make_job('b8-clean')
        self.task = Task(job=self.job, name='Clean task')
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()

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
