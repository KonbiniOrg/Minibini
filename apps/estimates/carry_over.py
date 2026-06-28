"""Atom carry-over from Worksheet to Job at acceptance time.

Triggered automatically when an Estimate transitions to ACCEPTED. Materializes the
job's worksheet atoms (PlanTasks, PlanMaterials) onto the Job (Tasks, Materials) via
the shared core, which handles provenance, idempotency (keyed on
Task.source_plan_task), and earmarks.

(Direct-estimate line items no longer originate atoms — documents are pure
projections of the Plan; the former line-item → Task/Material "Phase B" path was
removed in the estimate-projection phase.)
"""
from django.db import transaction


class AtomCarryOverService:

    @staticmethod
    @transaction.atomic
    def carry_over_for_estimate(estimate):
        """Create atoms on the Job from the estimate's worksheet (if any).

        Returns: {'tasks_created': int, 'materials_created': int}
        """
        job = estimate.job
        # The acceptance flow approves the job via a sibling signal (estimate_status_
        # changed_for_job) just before this one fires; refresh so we see the committed
        # status, not the stale cached instance, before materialize's state guard.
        job.refresh_from_db()

        from apps.estimates.models import EstWorksheet
        from apps.jobs.services import JobService
        worksheet = (
            EstWorksheet.objects.filter(job_id=job.pk)
            .order_by('-est_worksheet_id')
            .first()
        )
        if not worksheet:
            return {'tasks_created': 0, 'materials_created': 0}

        counts = JobService.materialize_worksheet_onto_job(job, worksheet)
        return {
            'tasks_created': counts['tasks_created'],
            'materials_created': counts['materials_created'],
        }
