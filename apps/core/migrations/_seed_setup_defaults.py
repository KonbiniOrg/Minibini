"""Seed the minimum machine state a fresh (migrate-only) database needs.

Lives in its own module so tests can import and re-run `seed` directly to
prove idempotency. Used by the seed_setup_defaults data migration; safe to
call any number of times — existing rows are never overwritten.
"""
import json

APPSTATE_DEFAULTS = {
    'job_counter': '0',
    'po_counter': '0',
}

CONFIGURATION_DEFAULTS = {
    'job_number_sequence': 'JOB-{year}-{counter:04d}',
    'po_number_sequence': 'PO-{year}-{counter:04d}',
    # Email service defaults (gmail); the tenant supplies address+password.
    # Seeded as REAL values, not UI placeholders — what you see works.
    'email_imap_server': 'imap.gmail.com',
    'email_smtp_host': 'smtp.gmail.com',
    'email_smtp_port': '587',
    # units_list is JSON-encoded at seed time from DEFAULT_UNITS below.
}


def seed(apps, schema_editor):
    from apps.core.units import DEFAULT_UNITS
    AppState = apps.get_model('core', 'AppState')
    Configuration = apps.get_model('core', 'Configuration')

    for key, value in APPSTATE_DEFAULTS.items():
        AppState.objects.get_or_create(key=key, defaults={'value': value})

    config = dict(CONFIGURATION_DEFAULTS)
    config['units_list'] = json.dumps(DEFAULT_UNITS)
    for key, value in config.items():
        Configuration.objects.get_or_create(key=key, defaults={'value': value})
