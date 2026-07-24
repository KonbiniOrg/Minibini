"""Seed setup defaults: AppState counters + numbering patterns + units.

A migrate-only database previously could not create a Job or PO at all —
the AppState counter rows were created only by fixtures. See
docs/plans/qbo-setup-import-spec.md Part 1.
"""
from django.db import migrations

from . import _seed_setup_defaults


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_loginevent'),
    ]

    operations = [
        migrations.RunPython(
            _seed_setup_defaults.seed, migrations.RunPython.noop,
        ),
    ]
