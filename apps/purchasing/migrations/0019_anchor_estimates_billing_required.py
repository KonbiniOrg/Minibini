# Ordering anchor (no schema operations) — second link in the 0018-0024
# chain (see 0018 for the full "why").
#
# Pulls in estimates only up through 0018 (TaskTemplate.rate_scheme, an FK
# to 'jobs.ratescheme' at that point) — deliberately *not* estimates' full
# leaf (0043), which would also drag in estimates.0026
# (RenameField tasktemplate.rate_scheme -> service_price, which requires
# jobs.0044 already applied). estimates.0018 itself already depends on
# ('jobs', '0029_planTask_billing_required') — so this link is not
# jobs-free, but it stops short of jobs.0044, so the next link can safely
# apply jobs' whole chain (including jobs.0044's RenameModel) with
# TaskTemplate.rate_scheme's FK already in state.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0018_anchor_expenses_before_pricelistitem_rename'),
        ('estimates', '0018_tasktemplate_billing_required'),
    ]

    operations = []
