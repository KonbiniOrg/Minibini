from decimal import Decimal
from django.test import TransactionTestCase


class TaskSourcePlanTaskBackfillTests(TransactionTestCase):
    """Verify migration 0022_backfill_task_source_plan_task copies source_plan_charge -> source_plan_task."""

    def test_backfill_links_task_to_plan_task(self):
        from apps.contacts.models import Contact, Business
        from apps.jobs.models import Job, PlanCharge, PlanTask, RateScheme, Task
        from apps.estimates.models import EstWorksheet

        # Build the object graph: Contact -> Job -> EstWorksheet -> PlanTask -> PlanCharge -> Task w/ source_plan_charge.
        contact = Contact.objects.create(first_name='Test', last_name='User')
        job = Job.objects.create(job_number='TEST-BF-001', name='Backfill Test Job', contact=contact)
        ws = EstWorksheet.objects.create(job=job)
        scheme = RateScheme.objects.create(
            name='Backfill Test Hourly', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('40.00'), unit_label='hour',
        )
        pt = PlanTask.objects.create(est_worksheet=ws, name='Backfill PT')
        pc = PlanCharge.objects.create(
            plan_task=pt, rate_scheme=scheme, estimated_billable_qty=Decimal('1.0'),
        )
        task = Task.objects.create(
            job=job, name='Backfill Task',
            source_plan_charge=pc,
        )

        # Ensure pre-state: source_plan_task_id is None.
        task.refresh_from_db()
        self.assertIsNone(task.source_plan_task_id)

        # Invoke the data migration's forward function directly.
        import importlib
        from django.apps import apps as app_registry
        migration_module = importlib.import_module(
            'apps.jobs.migrations.0022_backfill_task_source_plan_task'
        )
        migration_module.backfill_forward(app_registry, None)

        # Post-state: source_plan_task points at the same PlanTask.
        task.refresh_from_db()
        self.assertEqual(task.source_plan_task_id, pt.pk)
