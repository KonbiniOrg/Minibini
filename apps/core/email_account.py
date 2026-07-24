"""Per-tenant email account resolution: Configuration-first, env fallback.

The tenant's mail credentials live in Configuration rows (set from
Settings → Email); deployments that predate that keep working via the env
settings. One account drives both IMAP (inbound fetch) and SMTP (outbound).
"""
from django.conf import settings

# Configuration key → env-settings attribute
_KEYS = {
    'email_imap_server': ('imap_server', 'EMAIL_IMAP_SERVER'),
    'email_address': ('address', 'EMAIL_HOST_USER'),
    'email_password': ('password', 'EMAIL_HOST_PASSWORD'),
    'email_smtp_host': ('smtp_host', 'EMAIL_HOST'),
    'email_smtp_port': ('smtp_port', 'EMAIL_PORT'),
}


def email_account():
    """{'imap_server','address','password','smtp_host','smtp_port'} — each
    Configuration-first, env-settings fallback, '' when neither."""
    from apps.core.models import Configuration
    rows = dict(
        Configuration.objects.filter(key__in=_KEYS).values_list('key', 'value')
    )
    account = {}
    for config_key, (name, settings_attr) in _KEYS.items():
        value = rows.get(config_key) or getattr(settings, settings_attr, None)
        account[name] = str(value) if value not in (None, '') else ''
    return account


def email_configured():
    """True when the inbound-capable minimum is present: imap server,
    address, and password (from either source)."""
    account = email_account()
    return bool(account['imap_server'] and account['address']
                and account['password'])


def smtp_connection():
    """A Django mail connection for the resolved account, or None to use
    the default backend (env-configured deployments)."""
    from apps.core.models import Configuration
    db_configured = Configuration.objects.filter(
        key__in=('email_smtp_host', 'email_address', 'email_password'),
    ).count() == 3
    if not db_configured:
        return None
    from django.core.mail import get_connection
    account = email_account()
    return get_connection(
        host=account['smtp_host'],
        port=int(account['smtp_port'] or 587),
        username=account['address'],
        password=account['password'],
        use_tls=True,
    )
