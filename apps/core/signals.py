from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import LoginEvent


def _client_ip(request):
    if request is None:
        return None
    # X-Forwarded-For may be spoofed; trust it only behind a known reverse
    # proxy (nginx per docker-compose). Dev/tests don't care.
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
