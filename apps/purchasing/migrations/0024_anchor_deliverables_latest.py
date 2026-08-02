# Ordering anchor (no schema operations) — final link in the 0018-0024
# chain (see 0018 for the full "why").
#
# core.0029_singular_units depends on this single node instead of on
# estimates/purchasing/invoicing/inventory/deliverables/jobs directly as
# six siblings, so a fresh build walks all of them in the order this chain
# establishes rather than DFS's reverse-alphabetical sibling order.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0023_anchor_invoicing_latest'),
        ('deliverables', '0002_deliverablesnapshot'),
    ]

    operations = []
