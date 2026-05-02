from decimal import Decimal
from django.test import TransactionTestCase


class PlanChargeDataMigrationTests(TransactionTestCase):
    """Verify the data migration copies PlanCharge fields onto PlanTask.

    The fixture has zero PlanCharge rows, so we create one programmatically and
    then call copy_forward directly to verify it populates PlanTask correctly.
    """

    def test_data_is_copied(self):
        from apps.jobs.models import PlanTask, PlanCharge, RateScheme
        from apps.estimates.models import EstWorksheet
        from apps.jobs.models import Job
        from apps.contacts.models import Contact

        # --- Set up minimal data ---
        contact = Contact.objects.create(first_name='Test', last_name='User')
        job = Job.objects.create(job_number='MIGRATE-001', name='Migration Test Job', contact=contact)
        worksheet = EstWorksheet.objects.create(job=job)

        scheme = RateScheme.objects.create(
            name='Test Scheme',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'),
            unit_label='each',
        )

        pt = PlanTask.objects.create(
            est_worksheet=worksheet,
            name='Test Task',
        )

        pc = PlanCharge.objects.create(
            plan_task=pt,
            rate_scheme=scheme,
            active_modifiers=['rush'],
            estimated_billable_qty=Decimal('5.00'),
        )

        # Confirm fields on PlanTask are still NULL before migration runs
        pt.refresh_from_db()
        self.assertIsNone(pt.rate_scheme_id, "rate_scheme should be NULL before migration")
        self.assertIsNone(pt.estimated_billable_qty, "estimated_billable_qty should be NULL before migration")

        # --- Call copy_forward directly (simulates what the migration does) ---
        import importlib
        migration_module = importlib.import_module(
            'apps.jobs.migrations.0020_copy_plan_charge_to_plan_task'
        )
        copy_forward = migration_module.copy_forward
        from django.apps import apps as app_registry
        copy_forward(app_registry, None)

        # --- Verify fields were copied ---
        pt.refresh_from_db()
        self.assertEqual(pt.rate_scheme_id, scheme.pk)
        self.assertEqual(pt.active_modifiers, ['rush'])
        self.assertEqual(pt.estimated_billable_qty, Decimal('5.00'))
