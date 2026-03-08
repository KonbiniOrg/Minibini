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
    """
    from apps.jobs.models import Job

    job = estimate.job

    # Don't update completed or cancelled jobs
    if job.status in ['completed', 'cancelled']:
        return 0

    # Update job status if needed, respecting state transition rules
    if job.status != new_job_status:
        # If trying to go to 'approved' from 'draft', first go through 'submitted'
        if new_job_status == 'approved' and job.status == 'draft':
            job.status = 'submitted'
            job.save()
            # Now transition to approved
            job.status = 'approved'
            job.save()
            return 2  # Two transitions made
        else:
            job.status = new_job_status
            job.save()
            return 1

    return 0


@receiver(estimate_accepted)
def auto_earmark_inventory(sender, estimate, **kwargs):
    """
    Auto-create earmarks for inventoried materials when estimate is accepted.
    """
    from apps.inventory.services import InventoryService

    job = estimate.job
    preview = InventoryService.get_earmark_preview(job)

    if preview:
        earmark_data = [
            {
                'price_list_item_id': entry['price_list_item'].pk,
                'quantity': entry['needed_qty'],
            }
            for entry in preview
        ]
        InventoryService.create_earmarks_for_job(job, earmark_data)
