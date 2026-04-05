# Login Tracking

Date: 2026-04-04
Status: Design (not yet implemented)

## Purpose

Record a history of successful logins per user so the home page (and
potentially a future security/account-review screen) can display "your
recent logins over the last N days". Django's built-in
`User.last_login` is a single overwritable timestamp and does not meet
this need.

The immediate motivator is a "Recent Logins" widget on the user home
page, currently rendered as a placeholder (see
`frontend/src/components/home/RecentLoginsPlaceholder.svelte`).

## Non-goals

- Not a security/audit-log system for administrators. A separate,
  broader audit trail is out of scope.
- Not a session manager. No "log out this device" or concurrent-session
  enforcement here. (That may come later as a separate feature.)
- Not rate-limiting or brute-force protection.
- No tracking of failed login attempts in this first pass.

## Model

New model in `apps/core/models.py`:

```python
class LoginEvent(models.Model):
    user = models.ForeignKey('core.User', on_delete=models.CASCADE,
                             related_name='login_events')
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        db_table = 'login_events'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
        ]
```

Rationale:
- `CASCADE` on user: if a user is deleted, their login history goes
  with them. This is not an audit log for admins; it's a personal
  history tied to the account's existence.
- `ip_address` and `user_agent` are nullable/blank to tolerate unusual
  login paths (management commands, tests, proxy misconfigurations)
  without the signal handler crashing.
- Compound index on `(user, -timestamp)` supports the common query
  "most recent N logins for this user".

## Recording logins

Wire a signal handler to Django's `user_logged_in` signal. This fires
for every successful authentication path — DRF session login, the
Django admin, the `login()` view, and any custom code that calls
`django.contrib.auth.login()`.

```python
# apps/core/signals.py
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from .models import LoginEvent


def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or None


@receiver(user_logged_in)
def record_login_event(sender, request, user, **kwargs):
    LoginEvent.objects.create(
        user=user,
        ip_address=_client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT', '') if request else '')[:500],
    )
```

Connect the signal in `apps/core/apps.py`'s `ready()`.

### Edge cases
- `request` can be `None` when `login()` is called programmatically
  (e.g. tests). Handler must tolerate this.
- `HTTP_X_FORWARDED_FOR` may be spoofed; trust only if running behind a
  trusted reverse proxy. For dev/tests this is fine.
- User agent is truncated to 500 chars to avoid pathological headers.

## Retention

**First pass: query-time filter only.** The home page (and any other
consumer) queries with `timestamp__gte = now - timedelta(days=14)`.
Rows accumulate indefinitely.

For a job-shop app used by a small team this is negligible storage
(tens of rows per user per week). If it ever becomes a problem, add a
cron-driven management command:

```python
# apps/core/management/commands/prune_login_events.py
class Command(BaseCommand):
    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=90)
        LoginEvent.objects.filter(timestamp__lt=cutoff).delete()
```

Scheduling would live alongside the existing crontab config referenced
in CLAUDE.md. Not part of this design's initial scope.

## API

Extend `HomeService.get_home_data(user)` to include a `recent_logins`
key:

```json
{
  "assigned_tasks": [...],
  "recent_jobs": [...],
  "recent_logins": [
    {"timestamp": "2026-04-04T08:13:22Z", "ip_address": "192.0.2.10"},
    ...
  ]
}
```

Query:
```python
cutoff = timezone.now() - timedelta(days=14)
LoginEvent.objects.filter(
    user=user, timestamp__gte=cutoff,
).order_by('-timestamp')
```

No separate endpoint is needed initially — the home page is the only
consumer. If a future profile/security screen wants paginated access,
add `GET /api/login-events/` at that time.

### User agent in the response?

Omit from the API response by default. It's long, often uninformative
to end users ("Mozilla/5.0 (Macintosh; Intel Mac OS X…") and privacy-
adjacent. Keep it in the database for future support investigation,
but don't surface it in the home widget. IP address is enough for a
user to recognize "that was me at the shop vs. that was not".

Revisit if users actually ask for device/browser info.

## Frontend

Replace `RecentLoginsPlaceholder.svelte` with
`RecentLoginsList.svelte`:

- Takes a `logins` prop (the `recent_logins` array from `/api/home/`).
- Renders a plain list: each row shows timestamp (user's local
  formatting) and IP address.
- Empty state: "No logins in the last 14 days" — though in practice
  the current session itself should produce at least one row.

`Home.svelte` passes the new prop through the same way it does for
`recent_jobs`.

## Testing

- `LoginEvent` model: field defaults, index works (implicit in query).
- Signal handler: logging in via `self.client.login(...)` creates a
  row; logging out does not; programmatic `login()` with `request=None`
  does not crash.
- `/api/home/`: includes `recent_logins` scoped to the requesting
  user; excludes events older than 14 days; ordered most-recent first.
- Absence of failed-login tracking: an invalid login attempt does not
  create a row (sanity check, no behavior to add).

## Migration

`python manage.py makemigrations core` — creates the `login_events`
table and its indexes. Per CLAUDE.md, only the human operator applies
the migration.

## Open questions

- **Trusted proxy configuration for `X-Forwarded-For`.** If the app
  runs behind nginx (which it does per `docker-compose`), we should
  only trust `X-Forwarded-For` when the immediate upstream is a
  known proxy IP. For dev this doesn't matter; for prod, worth a
  follow-up. Could tie into a future `TRUSTED_PROXIES` setting.
- **Do we want to record logout too?** Not in this design. Logout is
  rarely interesting to users, and Django's `user_logged_out` signal
  doesn't always fire reliably (expired sessions, closed browsers).
- **Dev autologin noise.** The frontend's `?autologin` dev flow will
  create login events in development environments. Acceptable —
  production will see normal logins only.
