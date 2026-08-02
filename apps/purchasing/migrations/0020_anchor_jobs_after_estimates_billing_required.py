# Ordering anchor (no schema operations) — third link in the 0018-0024
# chain (see 0018 for the full "why").
#
# jobs' whole chain, including jobs.0044's RenameModel (RateScheme ->
# ServicePrice), applied with estimates.0018's FK to 'jobs.ratescheme'
# already resolved (via the previous link), so the rename's project-state
# fixup finds it.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0019_anchor_estimates_billing_required'),
        ('jobs', '0055_task_service_item'),
    ]

    operations = []
