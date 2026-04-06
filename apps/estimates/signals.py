import django.dispatch
from django.dispatch import receiver


# Custom signal for EstWorksheet status updates - only fired when needed
estimate_status_changed_for_worksheet = django.dispatch.Signal()

# Custom signal for Job status updates based on Estimate changes
estimate_status_changed_for_job = django.dispatch.Signal()

# Custom signal for estimate acceptance - triggers earmarking
estimate_accepted = django.dispatch.Signal()


@receiver(estimate_status_changed_for_worksheet)
def update_estworksheet_status(sender, estimate, new_worksheet_status, **kwargs):
    """
    Update EstWorksheet status based on Estimate status change.
    This is only called when a relevant status change occurs.
    """
    from apps.estimates.models import EstWorksheet

    # Single efficient UPDATE query - affects 0 rows if no worksheets exist
    updated_count = EstWorksheet.objects.filter(
        estimate=estimate
    ).exclude(
        status=new_worksheet_status  # Don't update if already correct status
    ).update(
        status=new_worksheet_status
    )

    # Return count for testing/logging purposes
    return updated_count


@receiver(estimate_status_changed_for_job)
def update_job_status(sender, estimate, new_job_status, **kwargs):
    """
    Update Job status based on Estimate status change.

    Business rules:
    - When estimate is accepted, job becomes approved (unless already complete)
    - When approved estimate is superseded, job becomes blocked (unless already complete)
    - Respects state transition rules: must go through intermediate states
    - Creates an action-type HistoryEntry for each status change
    """
    from apps.core.models import HistoryEntry, User
    from apps.jobs.models import Job

    job = estimate.job

    # Don't update completed or cancelled jobs
    if job.status in [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED]:
        return 0

    # Don't downgrade a job to a state it has already passed through
    # (e.g., don't move approved → submitted when sending a second estimate)
    JOB_STATUS_ORDER = [
        Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
    ]
    if (new_job_status in JOB_STATUS_ORDER and job.status in JOB_STATUS_ORDER and
            JOB_STATUS_ORDER.index(job.status) > JOB_STATUS_ORDER.index(new_job_status)):
        return 0

    # Update job status if needed, respecting state transition rules
    if job.status != new_job_status:
        system_user, _ = User.objects.get_or_create(
            username='system',
            defaults={'first_name': 'System', 'is_active': False},
        )
        if new_job_status == Job.STATUS_SUBMITTED:
            action_desc = f"Estimate {estimate.estimate_number} sent"
        elif new_job_status == Job.STATUS_APPROVED:
            action_desc = f"Estimate {estimate.estimate_number} accepted"
        else:
            action_desc = f"Estimate {estimate.estimate_number} status changed"

        # If trying to go to 'approved' from 'draft', first go through 'submitted'
        if new_job_status == Job.STATUS_APPROVED and job.status == Job.STATUS_DRAFT:
            old_status = job.status
            job.status = Job.STATUS_SUBMITTED
            job.save()
            HistoryEntry.objects.create(
                entry_type='action',
                object_type='job',
                object_id=job.pk,
                user=system_user,
                changes={'status': {'old': old_status, 'new': Job.STATUS_SUBMITTED}, '_action': action_desc},
            )
            # Now transition to approved
            job.status = Job.STATUS_APPROVED
            job.save()
            HistoryEntry.objects.create(
                entry_type='action',
                object_type='job',
                object_id=job.pk,
                user=system_user,
                changes={'status': {'old': Job.STATUS_SUBMITTED, 'new': Job.STATUS_APPROVED}, '_action': action_desc},
            )
            return 2  # Two transitions made
        else:
            old_status = job.status
            job.status = new_job_status
            job.save()
            HistoryEntry.objects.create(
                entry_type='action',
                object_type='job',
                object_id=job.pk,
                user=system_user,
                changes={'status': {'old': old_status, 'new': new_job_status}, '_action': action_desc},
            )
            return 1

    return 0
