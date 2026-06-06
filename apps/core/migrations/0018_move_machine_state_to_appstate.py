from django.db import migrations


# Machine-managed keys that move from Configuration → AppState.
MOVE_KEYS = ['job_counter', 'invoice_counter', 'po_counter', 'latest_email_date']

# Dead keys removed entirely:
#   - estimate numbering: estimates derive {job}-{ver}, not via NumberGenerationService
#   - tax: taxation is handled by QuickBooks, not the app
DELETE_KEYS = [
    'estimate_number_sequence', 'estimate_counter',
    'default_tax_rate', 'org_tax_multiplier',
]


def forwards(apps, schema_editor):
    Configuration = apps.get_model('core', 'Configuration')
    AppState = apps.get_model('core', 'AppState')
    for key in MOVE_KEYS:
        try:
            cfg = Configuration.objects.get(key=key)
        except Configuration.DoesNotExist:
            continue
        AppState.objects.update_or_create(key=key, defaults={'value': cfg.value})
        cfg.delete()
    Configuration.objects.filter(key__in=DELETE_KEYS).delete()


def backwards(apps, schema_editor):
    # Move the machine-state keys back into Configuration. The deleted dead keys
    # are not restored (they were dead).
    Configuration = apps.get_model('core', 'Configuration')
    AppState = apps.get_model('core', 'AppState')
    for key in MOVE_KEYS:
        try:
            st = AppState.objects.get(key=key)
        except AppState.DoesNotExist:
            continue
        Configuration.objects.update_or_create(key=key, defaults={'value': st.value})
        st.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_appstate'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
