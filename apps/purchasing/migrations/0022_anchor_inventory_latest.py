# Ordering anchor (no schema operations) — fifth link in the 0018-0024
# chain (see 0018 for the full "why").
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0021_anchor_estimates_latest'),
        ('inventory', '0034_inventoryitem_qbo_id'),
    ]

    operations = []
