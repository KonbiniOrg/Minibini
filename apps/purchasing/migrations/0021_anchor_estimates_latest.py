# Ordering anchor (no schema operations) — fourth link in the 0018-0024
# chain (see 0018 for the full "why").
#
# The rest of estimates (0019-0043), applied after jobs' whole chain (via
# the previous link), so estimates.0026's dependency on jobs.0044 resolves
# against an already-visited node instead of racing it.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0020_anchor_jobs_after_estimates_billing_required'),
        ('estimates', '0043_remove_changeorderlineitem_tax_rate_override_and_more'),
    ]

    operations = []
