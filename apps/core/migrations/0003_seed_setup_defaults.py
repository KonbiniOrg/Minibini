"""Seed setup defaults: AppState counters, numbering patterns, email service
defaults, and the units list.

A migrate-only database could otherwise not create a Job or PO at all — the
AppState counter rows used to come only from fixtures. Hand-authored survivor
of the 2026-10 migration consolidation (the logic lives in
apps/core/setup_defaults.py so tests can re-run it directly).
"""
from django.db import migrations

from apps.core import setup_defaults


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(setup_defaults.seed, migrations.RunPython.noop),
    ]
