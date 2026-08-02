# Ordering anchor (no schema operations) — sixth link in the 0018-0024
# chain (see 0018 for the full "why").
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0022_anchor_inventory_latest'),
        ('invoicing', '0021_alter_invoicelineitemsource_source_type'),
    ]

    operations = []
