"""Setup gates: which app areas are usable, derived live from actual data.

No stored flag (spec: docs/plans/qbo-setup-import-spec.md Part 3) — an area
is available iff its predicate passes right now. The sidebar greys
unavailable areas and shows each message as a floating callout; the Home
Help setup checklist reads the same statuses. Predicates are deliberately
cheap (EXISTS queries + one Configuration read).
"""
import json


def gate_status():
    """{'areas': {area: {'available': bool, 'message': str}},
    'last_pull_at': iso-string|None}

    Messages are the unlock path, empty string when available.
    """
    from apps.contacts.models import Business, Contact
    from apps.core.email_account import email_configured
    from apps.core.models import AccountingCategory, Configuration
    from apps.jobs.models import RateScheme

    email_ok = email_configured()
    catalog_ok = (AccountingCategory.objects.exists()
                  and RateScheme.objects.exists())
    jobs_ok = Contact.objects.exists()
    purchasing_ok = Business.objects.exists()

    def area(ok, message):
        return {'available': ok, 'message': '' if ok else message}

    areas = {
        'email': area(
            email_ok,
            'Add your email service configuration on Settings → Email.'),
        'catalog': area(
            catalog_ok,
            'Create at least one accounting category and rate scheme in '
            'Settings (or pull them from QuickBooks there).'),
        'jobs': area(
            jobs_ok,
            'Add a contact (or import your QBO customers in Contacts) '
            'first.'),
        'estimates': area(
            jobs_ok,
            'Estimates live on jobs — add a contact so a job can exist '
            'first.'),
        'invoices': area(
            jobs_ok,
            'Invoices live on jobs — add a contact so a job can exist '
            'first.'),
        'purchasing': area(
            purchasing_ok,
            'Add a vendor business (or import your QBO vendors in '
            'Contacts) first.'),
    }

    last_pull_at = None
    try:
        raw = Configuration.objects.get(key='qbo_import_snapshot').value
        last_pull_at = json.loads(raw).get('fetched_at')
    except Configuration.DoesNotExist:
        pass
    except (TypeError, ValueError):
        pass

    return {'areas': areas, 'last_pull_at': last_pull_at}
